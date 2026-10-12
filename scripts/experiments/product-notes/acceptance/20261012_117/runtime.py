"""Disposable current-checkout generation runner; imported safely by offline tests."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
import traceback
from types import SimpleNamespace

PREFIX = "PRODUCT_ACCEPTANCE_EVENT "
PROJECTS = ("dev-c0c8fdff34", "proj-0cc5c610b4")
PROJECT = PROJECTS[0]
SENSITIVE_KEYS = frozenset({
    "api_key", "base_url", "authorization", "credential", "credentials",
    "password", "secret", "access_token", "refresh_token", "pii_report",
})


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def plain(value):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {
            str(k): plain(v) for k, v in value.items()
            if str(k).lower() not in SENSITIVE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("Unsupported artifact value type")


def safe_error(exc):
    message = str(exc)
    for key, value in os.environ.items():
        if any(part in key.upper() for part in (
            "KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL",
        )) and len(value) >= 6:
            message = message.replace(value, "[redacted]")
    message = re.sub(r"https?://\S+", "[URL removed]", message)
    message = re.sub(r"\bsk-[\w-]+|Bearer\s+\S+", "[redacted]", message)
    message = re.sub(
        r"(?i)(api[_-]?key|password|secret|token)['\"]?\s*[:=]\s*['\"]?\S+",
        "[credential removed]", message,
    )
    # Provider response bodies can contain credentials not present in env.
    # Keep actionable names and frame locations, never their raw HTTP bodies.
    external = type(exc).__module__.split(".")[0] in {"openai", "httpx", "httpcore"}
    if external:
        message = "Provider exception detail suppressed"
    result = {
        "class": type(exc).__name__, "message": message[:240],
        "trace": [{"file": Path(frame.filename).name, "line": frame.lineno,
                   "function": frame.name}
                  for frame in traceback.extract_tb(exc.__traceback__)[-8:]],
    }
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        result["http_status"] = status
    return result


def emit(kind, **fields):
    print(PREFIX + json.dumps(plain({"type": kind, **fields}),
                             ensure_ascii=False), flush=True)


def fingerprints():
    result = {}
    base = Path("/data/projects")
    for pid in PROJECTS:
        for directory in ("workspace", "lancedb"):
            root = base / pid / directory
            if not root.is_dir():
                raise RuntimeError("Required existing project directory missing")
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    result[str(path.relative_to(base))] = sha256(path.read_bytes())
    return result


def integrity_summary(before, after):
    def digest(mapping):
        return sha256(json.dumps(mapping, sort_keys=True,
                                 separators=(",", ":")).encode())
    return {
        "file_count_before": len(before), "file_count_after": len(after),
        "sha256_before": digest(before), "sha256_after": digest(after),
        "changed": sorted(k for k in before.keys() | after.keys()
                          if before.get(k) != after.get(k)),
        "full": {"before": before, "after": after},
    }


def protected_path(value):
    if not isinstance(value, (str, bytes, os.PathLike)):
        return False
    resolved = os.path.realpath(os.fsdecode(value))
    return resolved == "/data" or resolved.startswith("/data/")


def guard_writes(event, args):
    if event == "open":
        path, mode, flags = args
        writable = bool(mode and any(c in mode for c in "wax+"))
        writable |= bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT
                                  | os.O_TRUNC | os.O_APPEND))
        if protected_path(path) and writable:
            raise RuntimeError("Acceptance forbids writes under /data")
    mutations = {
        "os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.chmod",
        "os.chown", "os.link", "os.symlink", "os.truncate", "os.utime",
    }
    if event in mutations and any(protected_path(a) for a in args):
        if event == "os.mkdir" and Path(args[0]).is_dir():
            return
        raise RuntimeError("Acceptance forbids filesystem mutation under /data")
    if event == "sqlite3.connect" and protected_path(args[0]):
        raise RuntimeError("Acceptance session hooks must avoid writable SQLite")


class ReadOnlyProxy:
    """Lance native mutations bypass Python open auditing, so block their API."""

    BLOCKED = frozenset({
        "add", "update", "delete", "merge_insert", "create_table",
        "drop_table", "drop_all_tables", "rename_table", "create_index",
        "create_fts_index", "create_scalar_index", "drop_index", "optimize",
        "cleanup_old_versions", "restore", "compact_files", "add_columns",
        "alter_columns", "drop_columns", "merge", "checkout_latest",
    })

    def __init__(self, wrapped):
        self.wrapped = wrapped

    def __len__(self):
        return len(self.wrapped)

    def __getattr__(self, name):
        if name in self.BLOCKED:
            def blocked(*args, **kwargs):
                raise RuntimeError("Acceptance forbids LanceDB mutation: " + name)
            return blocked
        attr = getattr(self.wrapped, name)
        if name == "open_table":
            return lambda *a, **kw: ReadOnlyProxy(attr(*a, **kw))
        return attr


def rebind(original, replacement):
    """Cover from-import aliases already bound before installing write hooks."""
    for module in list(sys.modules.values()):
        namespace = getattr(module, "__dict__", {})
        for name, value in list(namespace.items()):
            if value is original:
                namespace[name] = replacement


class Recorder:
    def __init__(self):
        self.calls = []
        self.attempts = []
        self.decisions = []
        self.label = ""

    def generate_wrapper(self, original):
        def wrapped(messages, *args, **kwargs):
            start = time.monotonic()
            attempt_start = len(self.attempts)
            item = {
                "label": self.label,
                "system_sha256": sha256(json.dumps([
                    m.get("content", "") for m in messages
                    if m.get("role") == "system"
                ], ensure_ascii=False, separators=(",", ":")).encode()),
                "message_count": len(messages),
                "max_tokens": kwargs.get("max_tokens"),
                "requested_model": kwargs.get("model_override"),
                "transport": "stream" if "stream" in original.__name__ else "sync",
            }
            try:
                reply = original(messages, *args, **kwargs)
                item.update({
                    "content": reply.content, "model": reply.model,
                    "tool_calls": plain(reply.tool_calls),
                    "usage": reply.usage.as_dict() if reply.usage else None,
                    "status": "ok",
                })
                return reply
            except Exception as exc:
                item.update(status="failed", error=safe_error(exc))
                raise
            finally:
                item["elapsed_seconds"] = round(time.monotonic() - start, 4)
                item["route_attempts"] = self.attempts[attempt_start:]
                successful = [a for a in item["route_attempts"]
                              if a.get("result") == "success"]
                item["provider"] = successful[-1].get("provider") if successful else None
                self.calls.append(item)
                emit("call", data=item)
        return wrapped


def generate_one(question, repeat, recorder, service, envelope_class, context_class):
    label = f"R{repeat}-{question['id']}"
    recorder.label = label
    call_start = len(recorder.calls)
    context = context_class(
        trace_id="accept117-" + label, session_id="accept117-" + label,
        message_type="user", channel="web", locale="zh-TW",
        persona_id="default", project_id=PROJECT, client_ip="",
        metadata={},
    )
    start = time.monotonic()
    prepared = service.prepare_generation(
        envelope_class(content=question["question"], context=context),
        reply_mode="fast", decision_debug=True,
    )
    emit("decision_context", label=label, data={
        "route": plain(prepared.route),
        "decision": prepared.turn_decision.to_debug_payload()
        if prepared.turn_decision else None,
        "decision_debug": prepared.turn_decision.to_debug_payload()
        if prepared.turn_decision else None,
        "calls": recorder.calls[call_start:],
        "input_language": prepared.input_language,
        "session_id": prepared.session_id,
        "prior_message_count": len(prepared.prior_messages),
        "reply_mode": prepared.reply_mode,
    })
    loop = service.execute_generation(prepared)
    elapsed = round(time.monotonic() - start, 4)
    final = service.finalize_generation(
        prepared, loop.reply, tool_steps=loop.tool_steps,
        response_time_s=elapsed, persist=False,
    )
    return {
        "id": question["id"], "repeat": repeat,
        "question": question["question"], "answer": loop.reply,
        "final": final, "tool_steps": loop.tool_steps,
        "decision": prepared.turn_decision.to_debug_payload()
        if prepared.turn_decision else None,
        "decision_debug": prepared.turn_decision.to_debug_payload()
        if prepared.turn_decision else None,
        "calls": recorder.calls[call_start:],
        "route": plain(prepared.route), "elapsed_seconds": elapsed,
    }


def install_hooks(recorder, private_root):
    import lancedb
    from core import chat_service, decision_router, llm_client
    from infra import db, project_context, usage_ledger
    from knowledge import doc_meta, workspace
    from memory import memory, retrieval
    from privacy import filter as privacy_filter
    from protocol import protocol_events
    from safety import observability

    # __file__ belongs to the private checkout; preserve the mounted data path.
    project_context._DATA_ROOT = Path("/data/projects")
    # Protocol helpers otherwise prefer the deployed /contracts mount.
    rebind(protocol_events._resolve_contracts_root,
           lambda: private_root / "contracts")

    def existing_workspace(project_id="default"):
        root = workspace.get_workspace_root(project_id)
        if not root.is_dir():
            raise RuntimeError("Workspace must already exist")
        return root

    rebind(workspace.ensure_workspace_scaffold, existing_workspace)

    def existing_db(ctx):
        if not ctx.lancedb_path.is_dir():
            raise RuntimeError("LanceDB must already exist")
        if ctx.project_id not in project_context._db_cache:
            project_context._db_cache[ctx.project_id] = ReadOnlyProxy(
                lancedb.connect(str(ctx.lancedb_path))
            )
        return project_context._db_cache[ctx.project_id]

    rebind(project_context.get_project_db, existing_db)

    def existing_tables(connection, version=None):
        names = set(connection.table_names())
        for name in db.TABLE_SEED_TEXTS:
            if db.resolve_vector_table_name(name, version) not in names:
                raise RuntimeError("Required vector table absent; seeding forbidden")

    rebind(db._create_missing_tables, existing_tables)
    rebind(memory.get_or_create_session, lambda session_id, *a, **kw:
           SimpleNamespace(session_id=session_id))
    rebind(memory.list_session_messages, lambda *a, **kw: [])
    rebind(chat_service.enforce_session_limits, lambda *a, **kw: None)
    # A fresh nonexistent session has no opt-out flag; avoid opening its store.
    rebind(memory.is_session_recall_disabled, lambda *a, **kw: False)

    metadata_cache = {}
    original_load = doc_meta.load_doc_meta

    def load_meta(project_id="default"):
        if project_id not in metadata_cache:
            metadata_cache[project_id] = original_load(project_id)
        return json.loads(json.dumps(metadata_cache[project_id]))

    def save_meta(metadata, project_id="default"):
        metadata_cache[project_id] = json.loads(json.dumps(metadata))

    rebind(doc_meta.load_doc_meta, load_meta)
    rebind(doc_meta.save_doc_meta, save_meta)
    noop = lambda *a, **kw: None
    rebind(retrieval.record_trace, noop)
    rebind(privacy_filter.detect_llm_messages_pii, noop)
    rebind(llm_client._record_llm_usage, noop)
    rebind(usage_ledger.record_usage_event, noop)

    def route_attempt(**kwargs):
        item = plain(kwargs)
        # Free-form error detail may include HTTP headers or private URLs.
        item = {k: v for k, v in item.items() if k in {
            "trace_id", "provider", "model", "hop_index", "result",
            "latency_ms", "chain_length", "reason",
        }}
        item.pop("reason", None)
        recorder.attempts.append(item)

    rebind(observability.record_route_attempt, route_attempt)
    rebind(observability.record_fallback_hop, noop)
    rebind(observability.record_chain_exhausted, noop)

    def decision_hop(**kwargs):
        item = {k: kwargs.get(k) for k in (
            "provider", "hop_id", "model", "purpose", "elapsed_ms", "status",
        )}
        item["usage"] = {
            k: decision_router._usage_int(kwargs.get("usage_obj"), k)
            for k in ("input_tokens", "output_tokens")
        }
        item["label"] = recorder.label
        recorder.decisions.append(item)
        emit("decision_call", data=item)

    rebind(decision_router._record_hop, decision_hop)
    original_generate = llm_client.generate_chat_turn
    rebind(original_generate, recorder.generate_wrapper(original_generate))
    original_stream = llm_client.stream_chat_turn
    rebind(original_stream, recorder.generate_wrapper(original_stream))
    return chat_service


def run(data, private_root):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(private_root / "brain" / "api"))
    sys.path.insert(1, str(private_root))
    logging.disable(logging.CRITICAL)
    recorder = Recorder()
    rows = []
    before = fingerprints()
    emit("baseline", data=before)
    status = "failed"
    error = None
    config = {"project": PROJECT, "persona": "default", "reply_mode": "fast"}
    try:
        sys.addaudithook(guard_writes)
        for path, expected in data["bundle_hashes"].items():
            if sha256((private_root / path).read_bytes()) != expected:
                raise RuntimeError("Private source bundle SHA mismatch")
        for pid in PROJECTS:
            base = Path("/data/projects") / pid / "workspace"
            for path, expected in data["snapshot_hashes"].items():
                if sha256((base / path).read_bytes()) != expected:
                    raise RuntimeError("Live source snapshot changed: " + path)
            live_notes = set(str(p.relative_to(base)) for p in
                             (base / "knowledge/products").glob("*.md"))
            expected_notes = {p for p in data["snapshot_hashes"]
                              if p.startswith("knowledge/products/")
                              and p.endswith(".md")}
            if len(live_notes) != 117 or live_notes != expected_notes:
                raise RuntimeError("Live 117-note set mismatch")
        emit("source_verified", data={
            "checkout": data["checkout"],
            "bundle_sha256": data["bundle_sha256"],
            "questions_sha256": data["questions_sha256"],
            "questions_frozen_at": data["questions_frozen_at"],
            "resolved_metadata_equal": data["behavior_parity"]["resolved_metadata_equal"],
        })
        service = install_hooks(recorder, private_root)
        if not Path(service.__file__).resolve().is_relative_to(private_root):
            raise RuntimeError("Generation imported outside private checkout")
        from config import get_settings
        cfg = get_settings()
        config.update({k: getattr(cfg, k, None) for k in (
            "llm_provider", "llm_model", "llm_temperature",
            "agent_loop_max_rounds", "forced_tool_max_tokens",
            "turn_decisions_enabled", "turn_decisions_timeout_seconds",
        )})
        emit("config", data=config)
        from protocol.message_envelope import MessageEnvelope, RequestContext
        from tools.context import active_persona_id, active_project_id
        active_project_id.set(PROJECT)
        active_persona_id.set("default")
        for repeat, question in data["schedule"]:
            row = generate_one(question, repeat, recorder, service,
                               MessageEnvelope, RequestContext)
            rows.append(row)
            emit("question", label=f"R{repeat}-{question['id']}", data=row)
        status = "completed"
    except Exception as exc:
        error = safe_error(exc)
        emit("failure", label=recorder.label, error=error)
        raise
    finally:
        after = fingerprints()
        integrity = integrity_summary(before, after)
        result = {
            "status": status, "error": error, "questions": rows,
            "calls": recorder.calls, "route_attempts": recorder.attempts,
            "config": config,
            "decision_calls": recorder.decisions, "integrity": integrity,
            "checkout": data["checkout"],
            "bundle_sha256": data["bundle_sha256"],
            "questions_sha256": data["questions_sha256"],
            "questions_frozen_at": data["questions_frozen_at"],
            "behavior_parity": data["behavior_parity"],
            "limitations": [
                "Current host checkout imported from private /tmp copy; /app untouched",
                "Direct prepare_generation/execute_generation/finalize_generation, not HTTP endpoint",
                "Fast reply mode and production speech/plain-text policies unchanged",
                "Normal user metadata; turn decision, prompts, tools and provider fallback unchanged",
                "New session per question/repeat; history empty, limits skipped, persist=False",
                "PII detector, usage, recall trace and route-audit file writes suppressed only in this process",
                "Auto document language writeback retained in process-local metadata shadow cache",
                "Raw mirror check may exit 1 for 99 language-cache differences; resolved parity separately recorded",
                "Python write audit plus LanceDB mutation proxy; native external writers detectable by final hashes",
            ],
        }
        emit("result", data=result)
        if integrity["changed"]:
            raise RuntimeError("Workspace/LanceDB changed; acceptance stopped")


if __name__ == "__acceptance_runtime__":
    run(DATA, PRIVATE_ROOT)

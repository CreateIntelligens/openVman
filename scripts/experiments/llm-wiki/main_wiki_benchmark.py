"""Compare main knowledge tools with Wiki recall in isolated, read-only agents."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from live_agent_stress import (
    HERE,
    answering_cases,
    classify_failure,
    dynamic_payload,
    output_path,
    validate_cases,
)


MAIN_FILES = (
    "config.py", "core/agent_loop.py", "core/llm_client.py",
    "core/provider_router.py", "core/prompt_builder.py",
    "core/prompt_templates.py", "core/fallback_chain.py",
    "core/gemini_credentials.py", "core/turn_reads.py",
    "memory/embedder.py", "memory/retrieval.py", "knowledge/doc_meta.py",
    "tools/tool_executor.py", "tools/tool_registry.py",
    "tools/builtin/knowledge_tools.py", "tools/builtin/product_tools.py",
)


def arm_order(rep, index):
    """Alternate paired order so one arm does not always receive warmed services."""
    return ["main", "wiki"] if (rep + index) % 2 == 0 else ["wiki", "main"]


def main_sources(ref):
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", ref + "^{commit}"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    hashes = {}
    for name in MAIN_FILES:
        source = subprocess.run(
            ["git", "show", f"{commit}:brain/api/{name}"],
            check=True, capture_output=True,
        ).stdout
        hashes[name] = hashlib.sha256(source).hexdigest()
    return commit, hashes


def validate_records(data, cases, reps):
    expected = {(c["id"], rep, arm) for c in cases
                for rep in range(reps) for arm in ("main", "wiki")}
    records = data.get("records", [])
    actual = [(r["id"], r["rep"], r["variant"]) for r in records]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("Missing, duplicate or extra paired benchmark records")
    if not data.get("config_unchanged") or data.get("readonly_check", {}).get("changed_paths") != []:
        raise ValueError("Benchmark has no successful readonly verification")


SCRIPT = r'''
import copy
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
import logging
from pathlib import Path
import sys
import time
import types
from unittest.mock import patch

logging.disable(logging.CRITICAL)
p = json.load(sys.stdin)
for name, expected in p["main_hashes"].items():
    if hashlib.sha256((Path("/app") / name).read_bytes()).hexdigest() != expected:
        raise RuntimeError("Container source differs from requested main commit: " + name)

def module(name, source):
    value = types.ModuleType(name)
    value.__file__ = "/app/" + name + ".py"
    sys.modules[name] = value
    exec(source, value.__dict__)
    return value

runtime = module("readonly_runtime", p["runtime"])
probe = module("latency_probe", p["probe"])
dynamic_module = module("benchmark_dynamic_recall", p["dynamic"]["implementation"])
gate = module("benchmark_source_gate", p["dynamic"]["gate_source"])
gate.__file__ = "/app/benchmark_source_gate.py"
claims = module("benchmark_claim_gate", p["dynamic"]["grounded_source"])
gate.detect_instruction = claims.detect_instruction

from config import get_settings
from core import agent_loop, llm_client, provider_router
from core.gemini_credentials import project_model_scope
from core.prompt_builder import build_chat_messages
from core.turn_decisions import TurnPolicy
from infra import project_context, usage_ledger
from knowledge.doc_meta import list_disabled_document_paths
from memory import embedder
from tools import tool_executor
from tools.builtin.knowledge_tools import search_knowledge_tool
from tools.builtin.product_tools import filter_products_tool
from tools.tool_registry import ToolRegistry

pid, persona = p["project_id"], p["persona_id"]
root = project_context.resolve_project_context(pid).project_root
before = runtime._manifest(root)
base = get_settings()
base_values = base.model_dump(mode="json")
production_encode = embedder.encode_query_with_fallback
production_tool = search_knowledge_tool()
current_arm, row_metrics = None, None
usage, calls = [], []
records, errors = [], []

def timed_tool(name, handler, arguments):
    start = time.perf_counter()
    try:
        return handler(arguments)
    finally:
        row_metrics[name + "_ms"] += (time.perf_counter() - start) * 1000
        row_metrics[name + "_calls"] += 1

def knowledge(arguments):
    if current_arm == "main":
        return timed_tool("knowledge", production_tool.handler, arguments)
    return timed_tool("knowledge", lambda args: wiki.search(
        args.get("queries", []), profile=p["wiki_profile"]), arguments)

def observed(name, original):
    def run(messages, **kwargs):
        start = time.perf_counter()
        event = {"kind":name}
        calls.append(event)
        try:
            reply = original(messages, **kwargs)
            event["model"] = reply.model
            return reply
        except Exception as exc:
            event["error_type"] = type(exc).__name__
            raise
        finally:
            event["time_ms"] = round((time.perf_counter() - start) * 1000, 2)
    return run

def collect_usage(**kwargs):
    usage.append({k:kwargs.get(k) for k in ("provider", "model", "latency_ms")})

with runtime.readonly_search(pid, persona_id=persona, reply_mode=p["mode"]) as formal, project_model_scope(pid), ExitStack() as stack:
    # The grid-search helper memoizes embeddings; main must retain its real path.
    stack.enter_context(patch.object(embedder, "encode_query_with_fallback", production_encode))
    registry = ToolRegistry()
    registry.register(replace(production_tool, handler=knowledge))
    product = filter_products_tool()
    registry.register(replace(product, handler=lambda args:timed_tool("products", product.handler, args)))
    stack.enter_context(patch.object(agent_loop, "get_tool_registry", lambda:registry))
    stack.enter_context(patch.object(tool_executor, "get_tool_registry", lambda:registry))
    stack.enter_context(patch.object(llm_client, "record_usage_event", collect_usage))
    stack.enter_context(patch.object(usage_ledger, "record_usage_event", collect_usage))
    stack.enter_context(patch.object(provider_router, "record_error_event", lambda **_:None))
    generate = observed("generate", llm_client.generate_chat_turn)
    stream = observed("stream", llm_client.stream_chat_turn)
    stack.enter_context(patch.object(llm_client, "generate_chat_turn", generate))
    stack.enter_context(patch.object(agent_loop, "generate_chat_turn", generate))
    stack.enter_context(patch.object(agent_loop, "stream_chat_turn", stream))
    started = time.perf_counter()
    wiki = dynamic_module.SearchRuntime(p["dynamic"], formal, gate)
    wiki_startup_ms = round((time.perf_counter() - started) * 1000, 2)
    policy = TurnPolicy(needs_knowledge=True, needs_web=False, needs_memory=False, auto_recall=False)
    settings = {k:getattr(get_settings(), k) for k in (
        "llm_provider", "llm_model", "chat_prefetch_knowledge_search",
        "chat_prefetch_knowledge_always", "embedding_thresholds")}
    for rep in range(p["reps"]):
        for index, case in enumerate(p["cases"]):
            order = ["main", "wiki"] if (rep + index) % 2 == 0 else ["wiki", "main"]
            for position, current_arm in enumerate(order):
                usage.clear(); calls.clear()
                trace_start = len(wiki.trace)
                row_metrics = {"knowledge_ms":0.0, "products_ms":0.0,
                               "knowledge_calls":0, "products_calls":0}
                row = {"id":case["id"], "rep":rep, "variant":current_arm,
                       "q":case["q"], "history":case.get("history", []),
                       "answer":"", "tool_steps":[], "error":None,
                       "pair_position":position, "source_access_gate":True,
                       "unauthorized_sources":[]}
                timer = probe.LatencyProbe()
                try:
                    messages = build_chat_messages(
                        case["q"], {"project_id":pid, "persona_id":persona,
                                    "metadata":case.get("metadata", {})},
                        case.get("history", []), allow_tools=True,
                        turn_policy=policy, preferred_language=case.get("lang"),
                    )
                    row["prompt_messages"] = copy.deepcopy(messages)
                    def capture(steps):
                        row["tool_steps"] = copy.deepcopy(steps)
                    result = agent_loop.run_agent_loop(
                        messages, persona_id=persona, project_id=pid,
                        allow_forced_knowledge_search=True, force_knowledge_search=True,
                        force_web_search=False, force_memory_search=False,
                        reply_mode=p["mode"], on_tool_round=capture, text_listener=timer,
                    )
                    row.update(answer=result.reply, tool_steps=result.tool_steps)
                    if not result.reply or not result.tool_steps:
                        raise RuntimeError("Missing answer or required knowledge step")
                    if any(json.loads(s["result"]).get("status") != "ok" for s in result.tool_steps):
                        raise RuntimeError("Read tool failed")
                except Exception as exc:
                    row["tool_steps"] = getattr(exc, "partial_steps", row["tool_steps"])
                    row["error"] = {"type":type(exc).__name__, "message":"Benchmark execution failed; original partial steps retained"}
                    errors.append({"id":case["id"], "rep":rep, "variant":current_arm, **row["error"]})
                row["latency"] = timer.finish(row["answer"])
                row["time_ms"] = row["latency"]["total_ms"]
                row["read_timing"] = {k:round(v, 2) for k,v in row_metrics.items()}
                row["llm_calls"] = copy.deepcopy(calls)
                row["usage"] = copy.deepcopy(usage)
                row["providers"] = sorted({u["provider"] for u in usage if u["provider"]})
                row["models"] = sorted({c["model"] for c in calls if c.get("model")})
                row["retrieval_trace"] = copy.deepcopy(wiki.trace[trace_start:])
                disabled = {v.removeprefix("knowledge/") for v in list_disabled_document_paths(pid)}
                paths = {path for step in row["tool_steps"]
                         for field in ("results", "related")
                         for item in json.loads(step["result"]).get("data", {}).get(field, [])
                         for path in item.get("source_paths", [item.get("path", "")])}
                row["unauthorized_sources"] = sorted(path for path in paths if path.removeprefix("knowledge/") in disabled)
                row["source_access_gate"] = not row["unauthorized_sources"]
                records.append(row)
                print(json.dumps({"event":"checkpoint", "record":row}, ensure_ascii=False), flush=True)

after = runtime._manifest(root)
if before != after or get_settings() is not base or base.model_dump(mode="json") != base_values:
    raise RuntimeError("Production files or settings changed")
print(json.dumps({"project_id":pid, "persona_id":persona, "records":records,
    "errors":errors, "config_unchanged":True,
    "readonly_check":{"file_count":len(before), "changed_paths":[]},
    "main_commit":p["main_commit"], "production_code_sha256":p["main_hashes"],
    "production_settings":settings, "wiki_profile":p["wiki_profile"],
    "reply_mode":p["mode"],
    "wiki_startup_ms":wiki_startup_ms, "answer_check_policy":"none",
    "answer_policy":"production", "history_policy":"production",
    "context_policy":"production", "experiment_embedding_cache":False,
    "scope":"Isolated main knowledge/product read path, alternating paired order; no HTTP decisions, sessions, memory, web, media or TTS; no checker or repair",
}, ensure_ascii=False))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cases", "snapshot", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--persona", default="default")
    parser.add_argument("--container", default="openvman-api-1")
    parser.add_argument("--main-ref", default="main")
    parser.add_argument("--mode", choices=("standard", "fast"), default="fast")
    parser.add_argument("--wiki-profile", choices=("focused_v1", "focused_v2"), default="focused_v2")
    parser.add_argument("--reps", type=int, default=2)
    args = parser.parse_args()
    if args.reps < 1:
        parser.error("--reps must be positive")
    cases = json.loads(args.cases.read_text())
    if not isinstance(cases, list) or not cases or len({c["id"] for c in cases}) != len(cases):
        parser.error("Cases must be a nonempty list with unique IDs")
    if any(not isinstance(c.get("q"), str) or not c["q"].strip() for c in cases):
        parser.error("Cases need nonempty questions")
    validate_cases(cases, {}, [])
    target = output_path(args.output, [args.cases])
    checkpoint = target.with_suffix(".checkpoint.jsonl")
    if args.snapshot.resolve() in (target, *target.parents):
        parser.error("Output must stay outside the input snapshot")
    if any(p.exists() for p in (target, checkpoint, target.with_suffix(".failure.json"))):
        parser.error("Choose new output and checkpoint paths")
    commit, hashes = main_sources(args.main_ref)
    dynamic = dynamic_payload(args.snapshot, args.project, [args.wiki_profile])
    dynamic["persona_id"] = args.persona
    sources = {name:(HERE/name).read_text() for name in (
        "readonly_runtime.py", "latency_probe.py", "focused_recall.py",
        "repaired_retrieval.py", "grounded_claims.py",
    )}
    payload = {"project_id":args.project, "persona_id":args.persona,
               "cases":answering_cases(cases), "dynamic":dynamic,
               "wiki_profile":args.wiki_profile, "reps":args.reps, "mode":args.mode,
               "main_commit":commit, "main_hashes":hashes,
               "runtime":sources["readonly_runtime.py"], "probe":sources["latency_probe.py"]}
    with checkpoint.open("x") as stream:
        process = subprocess.Popen(
            ["docker", "exec", "-i", "-w", "/app", args.container, "python", "-c", SCRIPT],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        process.stdin.write(json.dumps(payload, ensure_ascii=False))
        process.stdin.close()
        data = None
        count = 0
        for line in process.stdout:
            if not line.startswith("{"):
                continue
            item = json.loads(line)
            if item.get("event") == "checkpoint":
                row = item["record"]
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                count += 1
                print(json.dumps({"completed":count, "id":row["id"],
                                  "variant":row["variant"], "error":bool(row["error"])}), flush=True)
            else:
                data = item
        stderr = process.stderr.read()
        status = process.wait()
    if status or data is None:
        failure = {**classify_failure(stderr), "returncode":status,
                   "checkpoint_records":count}
        target.with_suffix(".failure.json").write_text(json.dumps(failure))
        print(json.dumps(failure))
        raise SystemExit("Benchmark failed; checkpoint retained; no accepted batch")
    validate_records(data, cases, args.reps)
    data["inputs_sha256"] = {str(args.cases):hashlib.sha256(args.cases.read_bytes()).hexdigest()}
    data["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    data["experiment_sources_sha256"] = {k:hashlib.sha256(v.encode()).hexdigest() for k,v in sources.items()}
    target.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(json.dumps({"answers":len(data["records"]), "errors":len(data["errors"]),
                      "readonly":data["readonly_check"], "main_commit":commit}))


if __name__ == "__main__":
    main()

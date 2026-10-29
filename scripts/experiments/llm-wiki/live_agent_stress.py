"""Run the production prompt builder, agent loop and provider chain without sessions."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from answer_policy import POLICIES, policy_metadata
from experiment_io import validate_output
from focused_recall import PROFILES
from history_query import HISTORY_POLICIES

HERE = Path(__file__).resolve().parent
OUTPUT_ROOT = Path(os.environ.get(
    "LLM_WIKI_OUTPUT_ROOT", Path.home() / "openvman-experiments/llm-wiki",
)).expanduser().resolve()
VARIANTS = ("prod_k3_t068", "mixed_multi")
DIFFERENCES = [
    "Calls production build_chat_messages and run_agent_loop directly; no HTTP/session persistence, turn decision classifier, PII stage, media selection, postprocessing or TTS.",
    "Forces knowledge prefetch; auto recall/web/memory/write/product-filter tools are disabled. Only the production search_knowledge schema and tool executor remain.",
    "Search handler returns the supplied candidate snapshot, including related chunks, for every knowledge tool call. History affects production planned_reads/prompt, but candidates are not recomputed from rewritten queries.",
    "Production project_model_scope, Backend project credential document and provider fallback routing are unchanged. Usage events and provider error learnings are collected in memory only.",
]


def experiment_differences(*, dynamic, answer_policy, history_policy,
                           context_policy, answer_check, check_model):
    result = list(DIFFERENCES)
    result[0] = result[0].replace("postprocessing", "production postprocessing")
    if dynamic:
        result[2] = (
            "Knowledge tools execute formal search and validated source recall "
            "using each actual runtime query; no precomputed per-case context."
        )
    if answer_policy != "production":
        result.append("Experimental system evidence policy: " + answer_policy)
    if history_policy != "production":
        result.append("Process-local history query policy: " + history_policy
                      + ("; applied to actual dynamic queries." if dynamic
                         else "; matched precomputed retrieval required."))
    if context_policy != "production":
        result.append("Process-local extractive history selector: " + context_policy)
    if answer_check != "none":
        result.append("Experimental final evidence check: " + answer_check
                      + "; requested checker model: " + (check_model or "project default")
                      + "; rejection and schema retries retained per record.")
    return result


CONTAINER_SCRIPT = r'''
import copy
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import itertools
import json
import logging
from pathlib import Path
import sys
import time
import types
from unittest.mock import patch

logging.disable(logging.CRITICAL)
payload = json.load(sys.stdin)
runtime = types.ModuleType("readonly_runtime")
sys.modules[runtime.__name__] = runtime
exec(payload["runtime"], runtime.__dict__)
answer_policy = types.ModuleType("experiment_answer_policy")
exec(payload["answer_policy_source"], answer_policy.__dict__)
policy_info = answer_policy.policy_metadata(payload["answer_policy"])
history_query = types.ModuleType("experiment_history_query")
exec(payload["history_query_source"], history_query.__dict__)
context_retention = types.ModuleType("experiment_context_retention")
sys.modules[context_retention.__name__] = context_retention
exec(payload["context_retention_source"], context_retention.__dict__)
answer_check = types.ModuleType("experiment_answer_check")
exec(payload["answer_check_source"], answer_check.__dict__)
dynamic_runtime = None

from config import get_settings
from core import agent_loop, llm_client, provider_router, turn_reads
from core import prompt_builder, prompt_templates, fallback_chain, gemini_credentials
from core.fallback_chain import build_fallback_chain
from core.gemini_credentials import project_model_scope, resolve_gemini_credential
from core.prompt_builder import build_chat_messages
from core.turn_decisions import TurnPolicy
from infra import project_context, usage_ledger
from knowledge.doc_meta import list_disabled_document_paths
from personas.personas import resolve_core_document_paths
from tools.builtin.knowledge_tools import search_knowledge_tool
from tools import tool_executor
from tools.tool_registry import ToolRegistry

pid, persona = payload["project_id"], payload["persona_id"]
base = get_settings()
base_values = base.model_dump(mode="json")
project_root = project_context.resolve_project_context(pid).project_root
before = runtime._manifest(project_root)
records, usage, attempts, llm_calls, errors = [], [], [], [], []
current_evidence = {}
current_variant, current_case = None, None
secrets = []

def scrub(text):
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text

def collect_usage(**kwargs):
    usage.append({k: kwargs.get(k) for k in ("provider", "model", "latency_ms", "raw")})

def route_attempt(**kwargs):
    attempts.append({k: kwargs.get(k) for k in ("provider", "model", "result", "reason", "hop_index")})

def candidate_handler(arguments):
    if dynamic_runtime is not None:
        return dynamic_runtime.search(arguments.get("queries", []), profile=current_variant)
    return {"table": "knowledge", "queries": arguments.get("queries", []),
            "embedding_versions": [], "results": copy.deepcopy(current_evidence["results"]),
            "related": copy.deepcopy(current_evidence["related"]),
            "citations": current_evidence.get("citations", [])}

def observed(original):
    def wrapped(messages, **kwargs):
        call = {"messages": copy.deepcopy(messages), "tools": copy.deepcopy(kwargs.get("tools"))}
        llm_calls.append(call)
        try:
            reply = original(messages, **kwargs)
        except Exception as exc:
            call["error_type"] = type(exc).__name__
            raise
        call.update(model=reply.model, tool_calls=[x.name for x in reply.tool_calls])
        return reply
    return wrapped

with runtime.readonly_search(pid, persona_id=persona) as formal_search, project_model_scope(pid), ExitStack() as stack:
    cfg = get_settings()
    cfg.chat_prefetch_knowledge_search = True
    cfg.chat_prefetch_knowledge_always = True
    if payload["dynamic"]:
        dynamic_module = types.ModuleType("experiment_dynamic_recall")
        exec(payload["dynamic"]["implementation"], dynamic_module.__dict__)
        gate = types.ModuleType("experiment_source_gate")
        gate.__file__ = "/app/experiment_source_gate.py"
        exec(payload["dynamic"]["gate_source"], gate.__dict__)
        claims = types.ModuleType("experiment_claim_gate")
        exec(payload["dynamic"]["grounded_source"], claims.__dict__)
        gate.detect_instruction = claims.detect_instruction
        dynamic_runtime = dynamic_module.SearchRuntime(payload["dynamic"], formal_search, gate)
    if payload["context_policy"] in ("retain_v1", "retain_v2"):
        from memory.auto_recall import strip_recall_noise
        def retained_history(messages):
            cleaned = [{**m, "content":strip_recall_noise(str(m.get("content", "")))} for m in messages]
            return context_retention.select_recent_messages(
                cleaned, current_question=current_case["q"],
                max_messages=max(cfg.short_term_memory_rounds * 2, 8),
                history_budget=cfg.prompt_history_char_budget,
                retain_subject_declarations=payload["context_policy"] == "retain_v2",
            )
        stack.enter_context(patch.object(prompt_builder, "select_recent_messages", retained_history))
    if payload["history_policy"] != "production":
        original_queries = turn_reads.knowledge_queries
        def retained_queries(current_text, previous_text):
            return history_query.expand_history_queries(
                original_queries(current_text, previous_text), current_text,
                previous_text, payload["history_policy"],
            )
        stack.enter_context(patch.object(turn_reads, "knowledge_queries", retained_queries))
    credential = resolve_gemini_credential()
    secrets.append(credential.api_key)
    chain = build_fallback_chain("readonly-agent-stress")
    secrets.extend(h.api_key for h in chain)
    if not chain:
        raise RuntimeError("Production project provider chain is empty")
    # Never initialize global skill discovery or any unrelated tool handler.
    registry = ToolRegistry()
    registry.register(replace(search_knowledge_tool(), handler=candidate_handler))
    stack.enter_context(patch.object(agent_loop, "get_tool_registry", lambda: registry))
    stack.enter_context(patch.object(tool_executor, "get_tool_registry", lambda: registry))
    stack.enter_context(patch.object(llm_client, "record_usage_event", collect_usage))
    stack.enter_context(patch.object(usage_ledger, "record_usage_event", collect_usage))
    stack.enter_context(patch.object(provider_router, "record_error_event", lambda **_: None))
    stack.enter_context(patch.object(llm_client, "record_route_attempt", route_attempt))
    stack.enter_context(patch.object(agent_loop, "stream_chat_turn", observed(llm_client.stream_chat_turn)))
    stack.enter_context(patch.object(agent_loop, "generate_chat_turn", observed(llm_client.generate_chat_turn)))
    documents = {
        name: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for name, path in resolve_core_document_paths(persona, pid).items() if path.is_file()
    }
    disabled_paths = sorted(set(payload["retrieval"].get("disabled_paths", [])) |
                            set(list_disabled_document_paths(pid)))
    policy = TurnPolicy(needs_knowledge=True, needs_web=False, needs_memory=False, auto_recall=False)
    for rep, case in itertools.product(range(payload["reps"]), payload["cases"]):
        for variant in payload["variants"]:
            current_variant, current_case = variant, case
            current_evidence = payload["retrieval"]["questions"][case["id"]][variant] if not dynamic_runtime else {"results":[],"related":[]}
            trace_start = len(dynamic_runtime.trace) if dynamic_runtime else 0
            usage.clear(); attempts.clear(); llm_calls.clear()
            start = time.perf_counter()
            row = {"id": case["id"], "rep": rep, "variant": variant, "q": case["q"],
                   "history": case.get("history", []), "answer": "", "tool_steps": []}
            row["answer_policy"] = policy_info
            row["history_policy"] = payload["history_policy"]
            row["context_policy"] = payload["context_policy"]
            row["unauthorized_sources"] = sorted({
                str(item.get("path", ""))
                for item in current_evidence["results"] + current_evidence["related"]
                if any(str(item.get("path", "")).removeprefix("knowledge/") ==
                       path.removeprefix("knowledge/") for path in disabled_paths)
            })
            row["source_access_gate"] = not row["unauthorized_sources"]
            def capture_tools(steps):
                row["tool_steps"] = copy.deepcopy(steps)
            try:
                messages = build_chat_messages(
                    case["q"], {"project_id": pid, "persona_id": persona,
                                "metadata": case.get("metadata", {})},
                    case.get("history", []), allow_tools=True, turn_policy=policy,
                    preferred_language=case.get("lang"),
                )
                messages = answer_policy.apply_policy(
                    messages, payload["answer_policy"],
                    total_char_budget=cfg.prompt_total_char_budget,
                )
                row["prompt_messages"] = copy.deepcopy(messages)
                result = agent_loop.run_agent_loop(
                    messages, persona_id=persona, project_id=pid,
                    allow_forced_knowledge_search=True, force_knowledge_search=True,
                    force_web_search=False, force_memory_search=False, reply_mode="standard",
                    on_tool_round=capture_tools,
                )
                row.update(answer=result.reply, tool_steps=result.tool_steps, error=None)
                if not result.reply or not result.tool_steps:
                    raise RuntimeError("Agent produced no answer or no knowledge tool step")
                if any(json.loads(s["result"]).get("status") != "ok" for s in result.tool_steps):
                    raise RuntimeError("A production tool execution failed")
                if payload["answer_check"] in ("evidence_check_v10", "evidence_check_v11", "evidence_check_v12", "evidence_check_v13"):
                    evidence = [item for step in result.tool_steps
                                for field in ("results","related")
                                for item in json.loads(step["result"]).get("data",{}).get(field,[])]
                    hint = str(case.get("lang", "")).lower()
                    language = "es" if hint.startswith("es") else "en" if hint.startswith("en") else "zh"
                    row["answer_check"] = answer_check.check_answer(
                        question=case["q"], history=messages[1:-1], evidence=evidence,
                        answer=result.reply, language=language, generate=lambda messages, **kwargs: llm_client.generate_chat_turn(
                            messages, model_override=payload["check_model"], **kwargs),
                        operational_rules=messages[0]["content"],
                        allow_repair=payload["answer_check"] in ("evidence_check_v11", "evidence_check_v12", "evidence_check_v13"),
                    )
                    row["answer"] = row["answer_check"]["final_answer"]
                    if row["answer_check"].get("error"):
                        raise RuntimeError("Answer evidence check failed; attempts retained")
            except Exception as exc:
                row["tool_steps"] = getattr(exc, "partial_steps", row["tool_steps"])
                row["error"] = {"type": type(exc).__name__, "message": scrub(str(exc))}
                errors.append({"id": case["id"], "variant": variant, **row["error"]})
            row.update(time_ms=round((time.perf_counter()-start)*1000, 2),
                       usage=copy.deepcopy(usage), provider_attempts=copy.deepcopy(attempts),
                       llm_calls=copy.deepcopy(llm_calls))
            if dynamic_runtime:
                row["retrieval_trace"] = copy.deepcopy(dynamic_runtime.trace[trace_start:])
                paths = {p for step in row["tool_steps"]
                         for item in json.loads(step["result"]).get("data",{}).get("results",[])
                         + json.loads(step["result"]).get("data",{}).get("related",[])
                         for p in item.get("source_paths", [item.get("path", "")])}
                disabled_now = {p.removeprefix("knowledge/") for p in list_disabled_document_paths(pid)}
                row["unauthorized_sources"] = sorted(p for p in paths if p.removeprefix("knowledge/") in disabled_now)
                row["source_access_gate"] = not row["unauthorized_sources"]
            row["providers"] = sorted({u["provider"] for u in usage if u["provider"]})
            row["models"] = sorted({u["model"] for u in usage if u["model"]})
            records.append(row)
            print(scrub(json.dumps({"event":"checkpoint","record":row},ensure_ascii=False)),flush=True)

after = runtime._manifest(project_root)
changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
if get_settings() is not base or base.model_dump(mode="json") != base_values:
    raise RuntimeError("Production settings changed")
if changed:
    raise RuntimeError("Production project files changed")
print(scrub(json.dumps({"project_id":pid,"persona_id":persona,"records":records,"errors":errors,
    "credential":credential.metadata(),"credential_configured":credential.configured,
    "configured_chain":[{"provider":h.provider,"model":h.model,"credential_source":h.credential_source} for h in chain],
    "workspace_documents":documents,"disabled_paths":disabled_paths,
    "readonly_check":{"file_count":len(before),"changed_paths":changed},
    "config_unchanged":True,"runtime_sha256":hashlib.sha256(payload["runtime"].encode()).hexdigest(),
    "production_code_sha256":{m.__name__:hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
        for m in (agent_loop,llm_client,provider_router,prompt_builder,prompt_templates,fallback_chain,gemini_credentials,tool_executor)},
    "answer_policy":policy_info,
    "answer_policy_source_sha256":hashlib.sha256(payload["answer_policy_source"].encode()).hexdigest(),
    "history_policy":payload["history_policy"],
    "history_query_source_sha256":hashlib.sha256(payload["history_query_source"].encode()).hexdigest(),
    "context_policy":payload["context_policy"],
    "answer_check_policy":payload["answer_check"],
    "answer_check_model_override":payload["check_model"],
    "answer_check_source_sha256":hashlib.sha256(payload["answer_check_source"].encode()).hexdigest(),
    "context_retention_source_sha256":hashlib.sha256(payload["context_retention_source"].encode()).hexdigest(),
    "retrieval_mode":"dynamic" if dynamic_runtime else "injected_snapshot",
    "dynamic_snapshot":payload["dynamic"].get("snapshot") if dynamic_runtime else None,
    "dynamic_source_sha256":hashlib.sha256(payload["dynamic"]["implementation"].encode()).hexdigest() if dynamic_runtime else None,
    "differences":payload["differences"]},ensure_ascii=False)))
'''


def validate_cases(cases, retrieval, variants):
    if not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Cases must be nonempty with unique IDs")
    for case in cases:
        if not isinstance(case.get("q"), str) or not case["q"].strip():
            raise ValueError("Each case needs a question")
        for message in case.get("history", []):
            if message.get("role") not in {"user", "assistant"} or not isinstance(message.get("content"), str):
                raise ValueError("History accepts user/assistant text messages only")
        for variant in variants:
            evidence = retrieval["questions"][case["id"]][variant]
            if not all(isinstance(evidence.get(key), list) for key in ("results", "related")):
                raise ValueError("Candidate results/related must be lists")


def answering_cases(cases):
    """Keep grading criteria out of the isolated answering process entirely."""
    fields = {"id", "q", "history", "metadata", "lang"}
    return [{key: value for key, value in case.items() if key in fields}
            for case in cases]


def dynamic_payload(snapshot_root, project_id, profiles):
    from snapshot_store import open_snapshot

    generation = open_snapshot(snapshot_root)
    manifest = json.loads((generation/"source_manifest.json").read_text())
    if manifest["project_id"] != project_id:
        raise ValueError("Snapshot project mismatch")
    gate = (HERE/"repaired_retrieval.py").read_text().split("BOOTSTRAP = r'''", 1)[0]
    gate = gate.replace("from experiment_io import validate_output", "").replace("from history_query import HISTORY_POLICIES", "")
    return {"snapshot":str(generation), "project_id":project_id, "persona_id":"default",
            "profiles":profiles, "source_manifest":manifest,
            "sections":json.loads((generation/"sections.json").read_text()),
            "sources":json.loads((generation/"sources.json").read_text()),
            "implementation":(HERE/"focused_recall.py").read_text(), "gate_source":gate,
            "grounded_source":(HERE/"grounded_claims.py").read_text()}


def output_path(value, inputs):
    path = validate_output(value, inputs=inputs)
    if OUTPUT_ROOT not in path.parents or path in {p.resolve() for p in inputs}:
        raise ValueError("Output must be under the external experiment root and differ from inputs")
    if path.exists():
        raise ValueError("Output exists; choose another path")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def classify_failure(stderr):
    """Expose fixed diagnostic categories without provider/request details."""
    checks = (
        ("project_data_changed", ("Project data changed during the experiment", "Production project files changed")),
        ("settings_changed", ("Production settings changed", "Settings values changed", "Settings singleton changed")),
        ("data_write_guard", ("Blocked data mutation:", "Experiment must only open existing tables")),
        ("search_failed", ("Search failed during the experiment", "Search failed; empty results are invalid")),
        ("credential_unavailable", ("GeminiCredentialUnavailable", "project Gemini credential unavailable")),
    )
    category = next((name for name, markers in checks if any(marker in stderr for marker in markers)),
                    "isolated_process_failed")
    kind = next((name for name in ("PermissionError", "AssertionError", "RuntimeError", "ValueError", "KeyError", "TypeError")
                 if any(line.startswith(name+":") for line in stderr.splitlines())), "unknown")
    return {"category":category,"exception_type":kind,"accepted":False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cases", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--retrieval", type=Path)
    source.add_argument("--snapshot", type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--persona", default="default")
    parser.add_argument("--variants", nargs="+", choices=("prod_k3_t068", "prod_k5_t068", "vector_only", "mixed_vector", "vector_multi", "mixed_multi", "mixed_single", "vector_char_budget", *PROFILES))
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--answer-policy", choices=POLICIES, default="production")
    parser.add_argument("--history-policy", choices=HISTORY_POLICIES, default="production")
    parser.add_argument("--context-policy", choices=("production", "retain_v1", "retain_v2"), default="production")
    parser.add_argument("--check-model", default=None)
    parser.add_argument("--answer-check", choices=("none", "evidence_check_v10", "evidence_check_v11", "evidence_check_v12", "evidence_check_v13"), default="none")
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())
    if isinstance(cases, dict):
        cases = cases["cases"]
    if args.reps < 1:
        parser.error("--reps must be positive")
    if args.ids:
        if not set(args.ids) <= {c["id"] for c in cases}:
            parser.error("Unknown case IDs")
        cases = [c for c in cases if c["id"] in args.ids]
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        cases = cases[:args.limit]
    args.variants = args.variants or (["safe_mixed", "focused_v1"] if args.snapshot else list(VARIANTS))
    if args.snapshot and not set(args.variants) <= set(PROFILES):
        parser.error("Dynamic retrieval accepts only recall profiles")
    dynamic = dynamic_payload(args.snapshot, args.project, args.variants) if args.snapshot else None
    if dynamic:
        dynamic["persona_id"] = args.persona
    retrieval = json.loads(args.retrieval.read_text()) if args.retrieval else {
        "project_id":args.project, "history_policy":args.history_policy,
        "questions":{c["id"]:{v:{"results":[],"related":[]} for v in args.variants} for c in cases}}
    if retrieval.get("project_id") != args.project:
        parser.error("Retrieval project mismatch")
    if retrieval.get("history_policy", "production") != args.history_policy:
        parser.error("Retrieval history policy mismatch")
    validate_cases(cases, retrieval, args.variants)
    inputs = [args.cases, args.retrieval] if args.retrieval else [args.cases, Path(dynamic["snapshot"])/"manifest.json"]
    target = output_path(args.output, inputs)
    differences = experiment_differences(
        dynamic=bool(dynamic), answer_policy=args.answer_policy,
        history_policy=args.history_policy, context_policy=args.context_policy,
        answer_check=args.answer_check, check_model=args.check_model,
    )
    payload = {"cases":answering_cases(cases),"retrieval":retrieval,"project_id":args.project,
               "persona_id":args.persona,"variants":args.variants,
               "reps":args.reps,
               "runtime":(HERE/"readonly_runtime.py").read_text(),"differences":differences,
               "answer_policy":args.answer_policy,
               "answer_policy_source":(HERE/"answer_policy.py").read_text(),
               "history_policy":args.history_policy,
               "history_query_source":(HERE/"history_query.py").read_text(),
               "context_policy":args.context_policy,
               "context_retention_source":(HERE/"context_retention.py").read_text(), "dynamic":dynamic}
    payload["check_model"] = args.check_model
    payload["answer_check"] = args.answer_check
    payload["answer_check_source"] = (HERE/"answer_check.py").read_text()
    runner_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    checkpoint = output_path(target.with_suffix(".checkpoint.jsonl"),
                             inputs)
    failure_path = output_path(target.with_suffix(".failure.json"),
                               inputs)
    process = subprocess.Popen(
        ["docker","exec","-i","-w","/app","openvman-api-1","python","-c",CONTAINER_SCRIPT],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
    )
    process.stdin.write(json.dumps(payload,ensure_ascii=False))
    process.stdin.close()
    data, count = None, 0
    with checkpoint.open("x") as stream:
        for line in process.stdout:
            if not line.startswith("{"):
                continue
            message = json.loads(line)
            if message.get("event") == "checkpoint":
                stream.write(json.dumps(message["record"],ensure_ascii=False)+"\n")
                stream.flush()
                count += 1
                row = message["record"]
                print(json.dumps({"completed":count,"id":row["id"],"rep":row["rep"],"variant":row["variant"],"error":bool(row["error"])},ensure_ascii=False),flush=True)
            else:
                data = message
    stderr = process.stderr.read()
    returncode = process.wait()
    if returncode or data is None:
        # Provider exceptions can contain request details; never echo raw stderr.
        failure = {**classify_failure(stderr),"returncode":returncode,"checkpoint_records":count}
        failure_path.write_text(json.dumps(failure,ensure_ascii=False,indent=1))
        raise SystemExit(json.dumps(failure,ensure_ascii=False))
    data["inputs_sha256"] = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    data["runner_sha256"] = runner_sha256
    if data.get("answer_policy") != policy_metadata(args.answer_policy):
        raise RuntimeError("Container answer policy did not match the requested policy")
    target.write_text(json.dumps(data,ensure_ascii=False,indent=1))
    print(json.dumps({"output":str(target),"answers":len(data["records"]),"errors":len(data["errors"]),"readonly_check":data["readonly_check"]},ensure_ascii=False))
    if data["errors"]:
        raise SystemExit("Some agent cases failed; inspect sanitized per-case errors")


if __name__ == "__main__":
    main()

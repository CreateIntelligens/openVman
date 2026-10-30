"""Compare main knowledge tools with Wiki recall in isolated, read-only agents."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from ablation_matrix import ARMS
from live_agent_stress import (
    HERE,
    answering_cases,
    classify_failure,
    dynamic_payload,
    output_path,
    validate_cases,
)
from pipeline_matrix import selected_arms


MAIN_FILES = (
    "config.py", "core/agent_loop.py", "core/llm_client.py",
    "core/provider_router.py", "core/prompt_builder.py",
    "core/prompt_templates.py", "core/fallback_chain.py",
    "core/gemini_credentials.py", "core/turn_reads.py",
    "memory/embedder.py", "memory/retrieval.py", "knowledge/doc_meta.py",
    "tools/tool_executor.py", "tools/tool_registry.py",
    "tools/builtin/knowledge_tools.py", "tools/builtin/product_tools.py",
)

OPTIONAL_MAIN_FILES = (
    "core/key_pool.py", "core/turn_budget.py", "knowledge/graph_rag.py",
    "memory/auto_recall.py", "safety/observability.py",
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
    names = list(MAIN_FILES)
    for name in OPTIONAL_MAIN_FILES:
        present = subprocess.run(
            ["git", "ls-tree", "--name-only", commit, "brain/api/" + name],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        if present:
            names.append(name)
    for name in names:
        source = subprocess.run(
            ["git", "show", f"{commit}:brain/api/{name}"],
            check=True, capture_output=True,
        ).stdout
        hashes[name] = hashlib.sha256(source).hexdigest()
    return commit, hashes


def inputs_unchanged(hashes):
    try:
        return all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
                   for path, digest in hashes.items())
    except OSError:
        return False


def validate_records(data, cases, reps, arms=("main", "wiki")):
    expected = {(c["id"], rep, arm) for c in cases
                for rep in range(reps) for arm in arms}
    records = data.get("records", [])
    actual = [(r["id"], r["rep"], r["variant"]) for r in records]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("Missing, duplicate or extra paired benchmark records")
    if not data.get("config_unchanged") or data.get("readonly_check", {}).get("changed_paths") != []:
        raise ValueError("Benchmark has no successful readonly verification")


SCRIPT = r'''
import copy
from contextlib import ExitStack, nullcontext
import dataclasses
from dataclasses import replace
import hashlib
import json
import logging
from pathlib import Path
import sys
import time
import threading
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
stages = module("stage_profiler", p["stage_profiler"])
matrix = module("ablation_matrix", p["ablation_matrix"])
pipeline_matrix = module("pipeline_matrix", p["pipeline_matrix"])
corpus_helper = module("corpus_recall", p["corpus_helper"])
pipeline_module = module("pipeline_runtime", p["pipeline_runtime"])
product_route = module("spec_product_route", p["spec_product_route"])
catalog_cache = module("catalog_cache", p["catalog_cache"])
pipeline_arms = p.get("pipeline_arms", pipeline_matrix.ARMS)
history = module("benchmark_history", p["history"])
retention = module("benchmark_retention", p["retention"])
answer_policy = module("benchmark_answer_policy", p["answer_policy"])
dynamic_module = module("benchmark_dynamic_recall", p["dynamic"]["implementation"])
gate = module("benchmark_source_gate", p["dynamic"]["gate_source"])
gate.__file__ = "/app/benchmark_source_gate.py"
claims = module("benchmark_claim_gate", p["dynamic"]["grounded_source"])
gate.detect_instruction = claims.detect_instruction

from config import get_settings
from core import agent_loop, llm_client, provider_router, prompt_builder, turn_reads
from core.gemini_credentials import project_model_scope
from core.prompt_builder import build_chat_messages
from core.turn_decisions import TurnPolicy
from infra import project_context, usage_ledger
from knowledge.doc_meta import list_disabled_document_paths
from memory import embedder
from memory.auto_recall import strip_recall_noise
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
profiler = None
profile_thread = threading.get_ident()
worker_profiles = {}
profile_lock = threading.Lock()
usage, calls = [], []
records, errors = [], []

def measure(name):
    if profiler is None:
        return nullcontext()
    if threading.get_ident() == profile_thread:
        return profiler.measure(name)
    with profile_lock:
        worker = worker_profiles.setdefault(threading.get_ident(), stages.Profiler(request_started_at=request_started))
    return worker.measure(name)

def profile_report():
    # Tool handlers run in workers; each lane has its own nesting stack.
    # Inclusive totals across lanes may overlap and must not be summed as wall time.
    result = {"summary":{}, "spans":[]}
    for lane, item in enumerate([profiler, *worker_profiles.values()]):
        report = item.report()
        offset = len(result["spans"])
        for span in report["spans"]:
            result["spans"].append({**span, "lane":lane,
                "parent":None if span["parent"] is None else offset + span["parent"]})
        for name, values in report["summary"].items():
            total = result["summary"].setdefault(name, {"count":0, "inclusive_ms":0, "self_ms":0})
            for field in total:
                total[field] += values[field]
    return result

def measured(name, original):
    def run(*args, **kwargs):
        with measure(name):
            return original(*args, **kwargs)
    return run

def timed_tool(name, handler, arguments):
    start = time.perf_counter()
    try:
        with measure(name):
            return handler(arguments)
    finally:
        row_metrics[name + "_ms"] += (time.perf_counter() - start) * 1000
        row_metrics[name + "_calls"] += 1

def knowledge(arguments):
    if p.get("pipelines"):
        if current_arm == "main":
            return timed_tool("knowledge", production_tool.handler, arguments)
        return timed_tool("knowledge", lambda args:pipeline.search(
            args.get("queries", []), {k:v for k,v in pipeline_arms[current_arm].items()
                                      if k in ("banks", "multi", "rewrite")}), arguments)
    settings = matrix.ARMS[current_arm] if p["ablation"] else {}
    if p["ablation"] and not settings.get("units"):
        supplied = dict(arguments)
        if settings.get("top_k"):
            supplied["top_k"] = settings["top_k"]
        return timed_tool("knowledge", production_tool.handler, supplied)
    if not p["ablation"] and current_arm == "main":
        return timed_tool("knowledge", production_tool.handler, arguments)
    return timed_tool("knowledge", lambda args: wiki.search(
        args.get("queries", []), profile=p["wiki_profile"],
        **({"controls":matrix.recall_controls(current_arm)} if p["ablation"] else {})), arguments)

def observed(name, original):
    def run(messages, **kwargs):
        start = time.perf_counter()
        event = {"kind":name, "request_chars":sum(len(str(m.get("content", ""))) for m in messages),
                 "tools_chars":len(json.dumps(kwargs.get("tools", []), ensure_ascii=False)),
                 "started_ms":(start - request_started) * 1000 if profiler else None}
        calls.append(event)
        try:
            with measure("llm_" + name):
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
    usage.append({k:kwargs.get(k) for k in ("provider", "model", "latency_ms", "raw")})

with runtime.readonly_search(pid, persona_id=persona, reply_mode=p["mode"]) as formal, project_model_scope(pid), ExitStack() as stack:
    # The grid-search helper memoizes embeddings; main must retain its real path.
    stack.enter_context(patch.object(embedder, "encode_query_with_fallback", production_encode))
    registry = ToolRegistry()
    registry.register(replace(production_tool, handler=knowledge))
    corpus_registry = ToolRegistry()
    corpus_registry.register(replace(production_tool, handler=knowledge))
    product = filter_products_tool()
    registry.register(replace(product, handler=lambda args:timed_tool("products", product.handler, args)))
    def products_enabled():
        return (not p["pipelines"] or current_arm == "main"
                or pipeline_arms[current_arm].get("products", False))
    def selected_registry():
        return registry if products_enabled() else corpus_registry
    stack.enter_context(patch.object(agent_loop, "get_tool_registry", selected_registry))
    stack.enter_context(patch.object(tool_executor, "get_tool_registry", selected_registry))
    original_product_line = prompt_builder.product_prompt_line
    stack.enter_context(patch.object(prompt_builder, "product_prompt_line",
        lambda project:original_product_line(project) if products_enabled() else ""))
    from knowledge.product_catalog import load_product_catalog
    from knowledge.workspace import get_workspace_root
    from tools.builtin import product_tools
    cache_enabled = p["pipelines"] and any(a.get("catalog_cache") for a in pipeline_arms.values())
    catalog_started = time.perf_counter()
    catalog_workspace = get_workspace_root(pid) if cache_enabled else None
    fingerprint_catalog = lambda:catalog_cache.catalog_source_fingerprint(catalog_workspace)
    catalog_sources_before = fingerprint_catalog() if cache_enabled else None
    product_catalog = load_product_catalog(pid) if p["pipelines"] else None
    verified_catalog = None
    if cache_enabled:
        verified_catalog = catalog_cache.VerifiedCatalogCache(
            pid, product_catalog, fingerprint=fingerprint_catalog,
        )
        if fingerprint_catalog() != catalog_sources_before:
            raise RuntimeError("Catalog sources changed during preparation")
    catalog_prepare_ms = round((time.perf_counter() - catalog_started) * 1000, 2)
    route_catalog = None if product_catalog is None else {
        "title": product_catalog.title, "key": product_catalog.key,
        "fields": {name:dataclasses.asdict(field)
                   for name,field in product_catalog.fields.items()},
        "products": [copy.deepcopy(product.values) for product in product_catalog.products],
    }
    def catalog_for_request(project_id):
        if (p["pipelines"] and pipeline_arms[current_arm].get("catalog_cache")):
            return timed_tool("catalog_cache", verified_catalog.load, project_id)
        return load_product_catalog(project_id)
    stack.enter_context(patch.object(product_tools, "load_product_catalog", catalog_for_request))
    def planned_product_route(case):
        previous = next((m.get("content", "") for m in reversed(case.get("history", []))
                         if m.get("role") == "user"), "")
        return product_route.route_spec_question(case["q"], previous,
                                                catalog=route_catalog)
    original_prefetched_turn = agent_loop._prefetched_knowledge_turn
    def prefetched_turn(arguments):
        turn = original_prefetched_turn(arguments)
        if p["pipelines"] and pipeline_arms[current_arm].get("force_products"):
            route = row.get("product_route")
            if route and route["required"]:
                turn = agent_loop._append_synthetic_call(
                    turn, "prefetch-spec-products", "filter_products", route["arguments"],
                )
        return turn
    stack.enter_context(patch.object(agent_loop, "_prefetched_knowledge_turn", prefetched_turn))
    stack.enter_context(patch.object(llm_client, "record_usage_event", collect_usage))
    stack.enter_context(patch.object(usage_ledger, "record_usage_event", collect_usage))
    stack.enter_context(patch.object(provider_router, "record_error_event", lambda **_:None))
    generate = observed("generate", llm_client.generate_chat_turn)
    stream = observed("stream", llm_client.stream_chat_turn)
    stack.enter_context(patch.object(llm_client, "generate_chat_turn", generate))
    stack.enter_context(patch.object(agent_loop, "generate_chat_turn", generate))
    stack.enter_context(patch.object(agent_loop, "stream_chat_turn", stream))
    for method, label in (("_rewrite", "query_rewrite"), ("_valid", "source_validation"),
                          ("_vector", "query_vector"), ("_hits", "vector_rank")):
        original = getattr(dynamic_module.SearchRuntime, method)
        stack.enter_context(patch.object(dynamic_module.SearchRuntime, method, measured(label, original)))
    stack.enter_context(patch.object(dynamic_module.LexicalIndex, "hits", measured("lexical_rank", dynamic_module.LexicalIndex.hits)))
    stack.enter_context(patch.object(dynamic_module, "exact_documents", measured("exact_document", dynamic_module.exact_documents)))
    stack.enter_context(patch.object(gate, "validate_sections", measured("validate_sections", gate.validate_sections)))
    stack.enter_context(patch.object(corpus_helper, "rank_hits", measured("corpus_rank", corpus_helper.rank_hits)))
    stack.enter_context(patch.object(corpus_helper.PreparedIndex, "rank", measured("corpus_rank", corpus_helper.PreparedIndex.rank)))
    stack.enter_context(patch.object(corpus_helper, "merge_ranks", measured("corpus_merge", corpus_helper.merge_ranks)))
    from tools.builtin import knowledge_tools
    stack.enter_context(patch.object(knowledge_tools, "_search_one", measured("formal_single_query", knowledge_tools._search_one)))
    stack.enter_context(patch.object(knowledge_tools, "_expand_via_graph", measured("graph_expand", knowledge_tools._expand_via_graph)))
    stack.enter_context(patch.object(embedder, "encode_query_with_fallback", measured("embedding_query", production_encode)))
    original_history = prompt_builder.select_recent_messages
    original_queries = turn_reads.knowledge_queries
    def history_enabled():
        return p["ablation"] and matrix.ARMS[current_arm].get("history", False)
    def retained_history(messages):
        if not history_enabled():
            return original_history(messages)
        cfg = get_settings()
        cleaned = [{**m, "content":strip_recall_noise(str(m.get("content", "")))} for m in messages]
        return retention.select_recent_messages(cleaned, current_question=current_case["q"],
            max_messages=max(cfg.short_term_memory_rounds * 2, 8),
            history_budget=cfg.prompt_history_char_budget, retain_subject_declarations=True)
    def retained_queries(current, previous):
        queries = original_queries(current, previous)
        return history.expand_history_queries(queries, current, previous, "subject_v3") if history_enabled() else queries
    stack.enter_context(patch.object(prompt_builder, "select_recent_messages", retained_history))
    stack.enter_context(patch.object(turn_reads, "knowledge_queries", retained_queries))
    started = time.perf_counter()
    wiki = dynamic_module.SearchRuntime(p["dynamic"], measured("formal_search", formal), gate)
    wiki_startup_ms = round((time.perf_counter() - started) * 1000, 2)
    pipeline = None
    pipeline_prepare_ms = 0
    if p["pipelines"]:
        started = time.perf_counter()
        pipeline = pipeline_module.Runtime(p["dynamic"], wiki, corpus_helper)
        pipeline_prepare_ms = round((time.perf_counter() - started) * 1000, 2)
    policy = TurnPolicy(needs_knowledge=True, needs_web=False, needs_memory=False, auto_recall=False)
    settings = {k:getattr(get_settings(), k) for k in (
        "llm_provider", "llm_model", "chat_prefetch_knowledge_search",
        "chat_prefetch_knowledge_always", "embedding_thresholds")}
    for rep in range(p["reps"]):
        for index, case in enumerate(p["cases"]):
            current_case = case
            order = pipeline_matrix.ordered_arms(index, rep, pipeline_arms) if p["pipelines"] else matrix.ordered_arms(index, rep) if p["ablation"] else (["main", "wiki"] if (rep + index) % 2 == 0 else ["wiki", "main"])
            for position, current_arm in enumerate(order):
                usage.clear(); calls.clear()
                if p["cold_queries"]:
                    wiki.query_cache.clear()
                    wiki.rewrite_cache.clear()
                trace_start = len(wiki.trace)
                pipeline_trace_start = len(pipeline.trace) if pipeline else 0
                row_metrics = {"knowledge_ms":0.0, "products_ms":0.0,
                               "knowledge_calls":0, "products_calls":0,
                               "catalog_cache_ms":0.0, "catalog_cache_calls":0}
                row = {"id":case["id"], "rep":rep, "variant":current_arm,
                       "q":case["q"], "history":case.get("history", []),
                       "answer":"", "tool_steps":[], "error":None,
                       "pair_position":position, "source_access_gate":True,
                       "unauthorized_sources":[]}
                request_started = time.perf_counter()
                timer = probe.LatencyProbe(request_started_at=request_started)
                profiler = stages.Profiler(request_started_at=request_started)
                worker_profiles = {}
                try:
                    with measure("prompt_build"):
                        route = None
                        arm_settings = pipeline_arms[current_arm] if p["pipelines"] else {}
                        row["answer_policy"] = arm_settings.get("policy", "production")
                        if arm_settings.get("force_products"):
                            route = planned_product_route(case)
                        row["product_route"] = copy.deepcopy(route)
                        messages = build_chat_messages(
                            case["q"], {"project_id":pid, "persona_id":persona,
                                        "metadata":case.get("metadata", {})},
                            case.get("history", []), allow_tools=True,
                            turn_policy=policy, preferred_language=case.get("lang"),
                        )
                        if p["ablation"] and matrix.ARMS[current_arm].get("policy"):
                            messages = answer_policy.apply_policy(messages, "evidence_v1", total_char_budget=get_settings().prompt_total_char_budget)
                            row["answer_policy"] = "evidence_v1"
                        if arm_settings.get("policy"):
                            messages = answer_policy.apply_policy(messages, arm_settings["policy"], total_char_budget=get_settings().prompt_total_char_budget)
                        if route and route["required"]:
                            messages = product_route.apply_route_policy(messages, route,
                                total_char_budget=get_settings().prompt_total_char_budget)
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
                    if route and route["required"] and not any(
                        step["name"] == "filter_products"
                        and step["tool_call_id"] == "prefetch-spec-products"
                        for step in result.tool_steps
                    ):
                        raise RuntimeError("Required product prefetch did not execute")
                    if not result.reply or not result.tool_steps:
                        raise RuntimeError("Missing answer or required knowledge step")
                    if any(json.loads(s["result"]).get("status") != "ok" for s in result.tool_steps):
                        raise RuntimeError("Read tool failed")
                except Exception as exc:
                    row["tool_steps"] = getattr(exc, "partial_steps", row["tool_steps"])
                    row["error"] = {"type":type(exc).__name__, "message":"Benchmark execution failed; original partial steps retained"}
                    errors.append({"id":case["id"], "rep":rep, "variant":current_arm, **row["error"]})
                row["latency"] = timer.finish(row["answer"])
                row["stages"] = profile_report()
                profiler = None
                row["time_ms"] = row["latency"]["total_ms"]
                row["read_timing"] = {k:round(v, 2) for k,v in row_metrics.items()}
                row["llm_calls"] = copy.deepcopy(calls)
                row["usage"] = copy.deepcopy(usage)
                row["providers"] = sorted({u["provider"] for u in usage if u["provider"]})
                row["models"] = sorted({c["model"] for c in calls if c.get("model")})
                row["retrieval_trace"] = copy.deepcopy(wiki.trace[trace_start:])
                if pipeline:
                    row["pipeline_trace"] = copy.deepcopy(pipeline.trace[pipeline_trace_start:])
                row["evidence_chars"] = sum(len(item.get("text", "")) for step in row["tool_steps"]
                    for field in ("results", "related")
                    for item in json.loads(step["result"]).get("data", {}).get(field, []))
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
    "pipeline_prepare_ms":pipeline_prepare_ms, "pipelines":p["pipelines"],
    "catalog_prepare_ms":catalog_prepare_ms,
    "answer_policy":"per_arm" if p["ablation"] or any(a.get("policy") for a in pipeline_arms.values()) else "production",
    "history_policy":"per_arm" if p["ablation"] else "production",
    "context_policy":"per_arm" if p["ablation"] else "production",
    "experiment_embedding_cache":False,
    "ablation":p["ablation"], "arms":pipeline_arms if p["pipelines"] else matrix.ARMS if p["ablation"] else {"main":{}, "wiki":{}},
    "cold_queries":p["cold_queries"],
    "prepared_vector_validation":p["pipelines"],
    "scope":"Isolated main knowledge/product read path, rotated and repeat-reversed order; no HTTP decisions, sessions, memory, web, media or TTS; no checker or repair",
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
    parser.add_argument("--ablation", action="store_true")
    parser.add_argument("--cold-queries", action="store_true")
    parser.add_argument("--pipelines", action="store_true")
    parser.add_argument("--compiled-sections", type=Path)
    parser.add_argument("--followup", action="store_true")
    parser.add_argument("--pipeline-arms", nargs="+")
    args = parser.parse_args()
    if args.ablation and args.wiki_profile != "focused_v2":
        parser.error("Ablation requires focused_v2 controls")
    if args.pipelines and (args.ablation or not args.compiled_sections):
        parser.error("Pipelines require compiled sections and cannot combine with ablation")
    if (args.followup or args.pipeline_arms) and not args.pipelines:
        parser.error("Follow-up controls require --pipelines")
    arms = selected_arms(args.followup, args.pipeline_arms)
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
    if args.pipelines:
        dynamic["compiled_sections"] = json.loads(args.compiled_sections.read_text())
    generation = Path(dynamic["snapshot"])
    inputs = [args.cases, *sorted(p for p in generation.rglob("*") if p.is_file())]
    if args.pipelines:
        inputs.append(args.compiled_sections)
    input_hashes = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    sources = {name:(HERE/name).read_text() for name in (
        "readonly_runtime.py", "latency_probe.py", "focused_recall.py",
        "repaired_retrieval.py", "grounded_claims.py",
        "stage_profiler.py", "ablation_matrix.py", "history_query.py",
        "context_retention.py", "answer_policy.py",
        "pipeline_matrix.py", "pipeline_runtime.py", "corpus_recall.py",
        "spec_product_route.py",
        "catalog_cache.py",
    )}
    payload = {"project_id":args.project, "persona_id":args.persona,
               "cases":answering_cases(cases), "dynamic":dynamic,
               "wiki_profile":args.wiki_profile, "reps":args.reps, "mode":args.mode,
               "main_commit":commit, "main_hashes":hashes,
               "runtime":sources["readonly_runtime.py"], "probe":sources["latency_probe.py"],
               "stage_profiler":sources["stage_profiler.py"], "ablation_matrix":sources["ablation_matrix.py"],
               "history":sources["history_query.py"], "retention":sources["context_retention.py"],
               "answer_policy":sources["answer_policy.py"],
               "pipeline_matrix":sources["pipeline_matrix.py"],
               "pipeline_runtime":sources["pipeline_runtime.py"],
               "corpus_helper":sources["corpus_recall.py"],
               "pipelines":args.pipelines,
               "pipeline_arms":arms,
               "spec_product_route":sources["spec_product_route.py"],
               "catalog_cache":sources["catalog_cache.py"],
               "ablation":args.ablation, "cold_queries":args.cold_queries}
    with checkpoint.open("x") as stream:
        process = subprocess.Popen(
            ["docker", "exec", "-i", "-w", "/app", args.container, "python", "-c", SCRIPT],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        input_error = None
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False))
        except (BrokenPipeError, OSError) as exc:
            input_error = type(exc).__name__
        finally:
            try:
                process.stdin.close()
            except (BrokenPipeError, OSError) as exc:
                input_error = input_error or type(exc).__name__
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
    if status or data is None or input_error:
        failure = {**classify_failure(stderr), "returncode":status,
                   "checkpoint_records":count}
        if input_error:
            failure["input_error_type"] = input_error
        target.with_suffix(".failure.json").write_text(json.dumps(failure))
        print(json.dumps(failure))
        raise SystemExit("Benchmark failed; checkpoint retained; no accepted batch")
    validate_records(data, cases, args.reps, arms if args.pipelines else ARMS if args.ablation else ("main", "wiki"))
    if not inputs_unchanged(input_hashes):
        raise SystemExit("Input snapshot changed; checkpoint retained, no accepted batch")
    data["inputs_sha256"] = input_hashes
    data["dynamic_snapshot"] = str(generation)
    data["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    data["experiment_sources_sha256"] = {k:hashlib.sha256(v.encode()).hexdigest() for k,v in sources.items()}
    target.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(json.dumps({"answers":len(data["records"]), "errors":len(data["errors"]),
                      "readonly":data["readonly_check"], "main_commit":commit}))


if __name__ == "__main__":
    main()

"""Fuse production-filtered results with source-validated extractive Wiki sections."""

import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

from experiment_io import validate_output
from history_query import HISTORY_POLICIES


HERE = Path(__file__).resolve().parent


def canonical_source(path):
    if not isinstance(path, str) or not path or "\\" in path:
        raise ValueError("invalid_source_path")
    pure = PurePosixPath(path)
    if pure.is_absolute() or len(pure.parts) < 2 or pure.parts[0] != "knowledge":
        raise ValueError("outside_knowledge")
    if any(part in (".", "..") for part in path.split("/")) or str(pure) != path:
        raise ValueError("noncanonical_source_path")
    return path


def validate_section(section, manifest, *, project_id, persona_id,
                     workspace_root, disabled_paths, current_source_personas):
    """Fail closed if any dependency, identity or reference has drifted."""
    try:
        if manifest.get("project_id") != project_id or section.get("project_id") != project_id:
            raise ValueError("cross_project")
        if section.get("persona_id") != persona_id:
            raise ValueError("cross_persona")
        if not isinstance(section.get("id"), str) or not section["id"]:
            raise ValueError("missing_section_id")
        if not isinstance(section.get("text"), str) or not section["text"].strip():
            raise ValueError("empty_section")
        paths, refs, hashes = (section.get(key) for key in
                               ("source_paths", "source_refs", "source_hashes"))
        if not isinstance(paths, list) or not paths or len(paths) != len(set(paths)):
            raise ValueError("invalid_dependencies")
        if not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r for r in refs):
            raise ValueError("invalid_refs")
        if not isinstance(hashes, dict) or set(hashes) != set(paths):
            raise ValueError("dependency_hash_keys_mismatch")
        sources = manifest.get("sources", {})
        supported_refs = set()
        root = Path(workspace_root).resolve()
        disabled = {canonical_source(path) for path in disabled_paths}
        for raw_path in paths:
            path = canonical_source(raw_path)
            if path in disabled:
                raise ValueError("disabled_source")
            personas = current_source_personas.get(path)
            if not isinstance(personas, list) or not personas:
                raise ValueError("current_source_metadata_missing")
            # The formal filter grants blank/global chunks to every persona.
            # A grouped section spans a whole source, so a single restricted
            # foreign chunk invalidates it even if another chunk is global.
            if any(not isinstance(value, str) or value.strip() not in
                   ("", "global", persona_id) for value in personas):
                raise ValueError("current_source_persona_denied")
            source = sources.get(path)
            if not isinstance(source, dict):
                raise ValueError("source_not_in_manifest")
            if source.get("persona_id") != persona_id:
                raise ValueError("source_persona_changed")
            source_refs = source.get("refs")
            if not isinstance(source_refs, list) or not set(refs).intersection(source_refs):
                raise ValueError("dependency_has_no_section_ref")
            supported_refs.update(source_refs)
            expected = source.get("sha256")
            if not isinstance(expected, str) or len(expected) != 64 or hashes[path] != expected:
                raise ValueError("snapshot_hash_mismatch")
            lexical = root / path
            try:
                actual = lexical.resolve(strict=True)
            except (FileNotFoundError, RuntimeError):
                raise ValueError("source_missing_or_renamed") from None
            if root not in actual.parents or actual != lexical:
                raise ValueError("source_symlink_or_escape")
            if not actual.is_file():
                raise ValueError("source_not_file")
            if hashlib.sha256(actual.read_bytes()).hexdigest() != expected:
                raise ValueError("source_modified")
        if not set(refs) <= supported_refs:
            raise ValueError("unknown_ref")
    except (OSError, TypeError, ValueError) as exc:
        return False, str(exc)
    return True, "ok"


def validate_sections(sections, manifest, **context):
    accepted, rejected, seen = [], [], set()
    for section in sections:
        if section.get("id") in seen:
            raise ValueError("Duplicate section IDs")
        seen.add(section.get("id"))
        valid, reason = validate_section(section, manifest, **context)
        if valid:
            accepted.append(copy.deepcopy(section))
        else:
            rejected.append({"id": section.get("id"), "reason": reason})
    return accepted, rejected


def merge_ranklists(grouped, merge_search_results, limit=5):
    """Fuse ranks only, preserving the first copy of an exact duplicate text."""
    first, normalized = {}, []
    for label, records in grouped:
        ranked, within_list = [], set()
        for record in records:
            text = record["text"]
            key = hashlib.sha256(text.encode()).hexdigest()
            if key in within_list:
                continue
            within_list.add(key)
            first.setdefault(key, copy.deepcopy(record))
            # Production score order is already resolved by its own search tool.
            # Synthetic ranks keep L2 and production RRF scores incomparable.
            ranked.append({**record, "chunk_id": key, "_score": -len(ranked)})
        normalized.append((label, ranked))
    fused = merge_search_results(normalized, limit=len(first))
    result = []
    for record in fused[:limit]:
        original = copy.deepcopy(first[record["chunk_id"]])
        original["_mixed_rrf_score"] = record["_rrf_score"]
        original["matched_queries"] = record["matched_queries"]
        result.append(original)
    return result


BOOTSTRAP = r'''
import copy
import hashlib
import json
from pathlib import Path
import sys
import types
from unittest.mock import patch

import numpy as np

payload = json.load(sys.stdin)
runtime = types.ModuleType("readonly_runtime")
sys.modules[runtime.__name__] = runtime
exec(payload["runtime"], runtime.__dict__)
candidate = types.ModuleType("repaired_retrieval_runtime")
candidate.__file__ = "/app/repaired_retrieval_runtime.py"
exec(payload["implementation"], candidate.__dict__)
history_query = types.ModuleType("experiment_history_query")
exec(payload["history_query_source"], history_query.__dict__)

from config import get_settings
from core.turn_reads import knowledge_queries, previous_user_text
from infra.project_context import resolve_project_context
from infra.db import get_knowledge_table, parse_record_metadata
from knowledge.doc_meta import list_disabled_document_paths
from memory.embedder import get_embedder
from tools.builtin import knowledge_tools
from tools.search_helpers import merge_search_results
from personas.personas import normalize_persona_id

pid, persona = payload["project_id"], payload["persona_id"]
original_cfg = get_settings()
original_values = original_cfg.model_dump(mode="json")
ctx = resolve_project_context(pid)
before = runtime._manifest(ctx.project_root)
out, audit = {}, []
with runtime.readonly_search(pid, persona_id=persona) as search:
    from memory.embedder import encode_query_with_fallback
    cfg = get_settings()
    cfg_values = cfg.model_dump(mode="json")
    disabled = sorted(list_disabled_document_paths(pid))
    def current_personas():
        table = get_knowledge_table(pid)
        records = table.search().select(["path","metadata"]).limit(table.count_rows()).to_list()
        by_path = {}
        for record in records:
            metadata = parse_record_metadata(record)
            path = str(metadata.get("path", "")).strip() or str(record.get("path", "")).strip()
            if not path.startswith("knowledge/"):
                continue
            value = str(metadata.get("persona_id", "")).strip()
            if value not in ("", "global"):
                value = normalize_persona_id(value)
            by_path.setdefault(path, []).append(value)
        return by_path, table.version
    source_personas, persona_table_version = current_personas()
    sections, rejected = candidate.validate_sections(
        payload["sections"], payload["source_manifest"], project_id=pid,
        persona_id=persona, workspace_root=ctx.workspace_root,
        disabled_paths=disabled,
        current_source_personas=source_personas,
    )
    identity = cfg.resolved_embedding_write_identity
    wiki_vectors = None
    if sections:
        vectors, spec, _ = get_embedder().encode_with_metadata(
            [s["text"] for s in sections], input_type="document",
            forced_identity=identity, titles=[s["title"] for s in sections],
        )
        if spec.get("identity") != identity:
            raise ValueError("Wiki embedding identity differs")
        wiki_vectors = np.asarray(vectors, dtype=np.float32)
        if not np.allclose(np.linalg.norm(wiki_vectors, axis=1), 1, atol=.005):
            raise ValueError("Wiki vectors are not unit normalized")

    def mark_production(rows):
        marked = []
        for row in rows:
            path = candidate.canonical_source(row.get("path", ""))
            marked.append({**copy.deepcopy(row), "src":"production",
                           "source_paths":[path],
                           "source_refs":["production:" + str(row.get("chunk_id", row.get("id", path)))],
                           "refs":["production:" + str(row.get("chunk_id", row.get("id", path)))],
                           "project_id":pid,"persona_id":persona})
        return marked

    def wiki_hits(query, current_sections):
        if not sections:
            return []
        route = encode_query_with_fallback(query, project_id=pid, table_names=("knowledge",))
        if cfg.resolve_embedding_identity(route.version) != identity:
            raise ValueError("Query/wiki embedding identities differ")
        vector = np.asarray(route.vector, dtype=np.float32)
        if not np.isclose(np.linalg.norm(vector), 1, atol=.005):
            raise ValueError("Query is not unit normalized")
        distances = ((wiki_vectors-vector)**2).sum(axis=1)
        hits = []
        valid_ids = {s["id"] for s in current_sections}
        for i in np.argsort(distances):
            section = sections[i]
            if section["id"] not in valid_ids or 1-float(distances[i])/2 < .68:
                continue
            hits.append({**copy.deepcopy(section), "src":"wiki",
                "path":"wiki/"+section["slug"], "chunk_id":"wiki:"+section["id"],
                "refs":section["source_refs"], "_distance":float(distances[i]),
                "trust_boundary":"untrusted_reference_data"})
            if len(hits) == 5:
                break
        return hits

    for case in payload["cases"]:
        previous = previous_user_text(case.get("history", []), case["q"])
        queries = history_query.expand_history_queries(
            knowledge_queries(case["q"], previous), case["q"], previous,
            payload["history_policy"],
        )
        variants = {}
        for name, k in (("prod_k3_t068",3),("prod_k5_t068",5)):
            formal = search(case["q"], top_k=k, threshold=.68, queries=queries)
            variants[name] = {key:copy.deepcopy(formal[key]) for key in ("results","related","queries")}
        # Per-query official results are captured after persona/disabled/language/
        # threshold/dedup processing; no LanceDB table scan is used here.
        captured = []
        original_one = knowledge_tools._search_one
        def capture(*args, **kwargs):
            records, version, vector = original_one(*args, **kwargs)
            captured.append((args[1], mark_production(records)))
            return records, version, vector
        with patch.object(knowledge_tools, "_search_one", capture):
            formal = search(case["q"], top_k=5, threshold=.68, queries=queries)
        now_disabled = sorted(list_disabled_document_paths(pid))
        now_personas, now_table_version = current_personas()
        valid, dropped = candidate.validate_sections(
            sections, payload["source_manifest"], project_id=pid, persona_id=persona,
            workspace_root=ctx.workspace_root, disabled_paths=now_disabled,
            current_source_personas=now_personas,
        )
        wiki_ranked = [("wiki:"+query, wiki_hits(query, valid)) for query in queries]
        fused = candidate.merge_ranklists(
            [("production:"+q, rows) for q, rows in captured]+wiki_ranked,
            merge_search_results, limit=5,
        )
        # Formal graph neighbours retain the production access filters. They are
        # kept in related just as the official tool exposes them.
        related = mark_production(formal["related"])
        used = {r["text"] for r in fused}
        related = [r for r in related if r["text"] not in used]
        variants["safe_mixed"] = {"results":fused,"related":related,"queries":queries}
        audit.append({"id":case["id"],"wiki_sections_valid_now":len(valid),"dropped_now":dropped,
            "persona_table_version":now_table_version,
            "source_personas_sha256":hashlib.sha256(json.dumps(now_personas,sort_keys=True).encode()).hexdigest()})
        out[case["id"]] = variants
    assert cfg.model_dump(mode="json") == cfg_values
after = runtime._manifest(ctx.project_root)
changed = sorted(k for k in before.keys()|after.keys() if before.get(k)!=after.get(k))
if changed or get_settings() is not original_cfg or original_cfg.model_dump(mode="json")!=original_values:
    raise RuntimeError("Production files or settings changed")
print(json.dumps({"project_id":pid,"persona_id":persona,"questions":out,
    "disabled_paths":disabled,"readonly_check":{"file_count":len(before),"changed_paths":changed},
    "config_unchanged":True,"accepted_sections":len(sections),"rejected_sections":rejected,
    "dependency_audit":audit,"embedding_identity":identity,
    "current_source_personas":{path:{"chunk_count":len(values),"personas":sorted(set(values))}
        for path,values in source_personas.items() if path in payload["source_manifest"]["sources"]},
    "persona_table_version":persona_table_version,
    "persona_policy":"Every current indexed chunk of each source must be visible: blank/global/requested persona; missing or mixed foreign chunks reject the whole section",
    "fusion":"Per-query production filtered primary ranks + Wiki cosine>=.68 top5 ranks; RRF top5; exact-text first-copy dedup; production filtered graph remains related",
    "history_policy":payload["history_policy"],
    "history_query_source_sha256":hashlib.sha256(payload["history_query_source"].encode()).hexdigest(),
    "snapshot":payload["snapshot"],"snapshot_sha256":payload["snapshot_sha256"]},ensure_ascii=False))
'''


def main():
    from snapshot_store import open_snapshot

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--history-policy", choices=HISTORY_POLICIES, default="production")
    args = parser.parse_args()
    # Retain one validated generation for this whole run, including every
    # payload hash; merely resolving current would accept altered wiki text.
    snapshot = open_snapshot(args.snapshot)
    inputs = [args.cases, snapshot/"sections.json", snapshot/"source_manifest.json"]
    output = validate_output(args.output, inputs=inputs)
    if output.exists():
        parser.error("Output exists; use a new path")
    cases = json.loads(args.cases.read_text())
    if not cases or len({q["id"] for q in cases}) != len(cases) or any(not q["q"].strip() for q in cases):
        parser.error("Cases must have unique IDs and nonempty questions")
    manifest = json.loads((snapshot/"source_manifest.json").read_text())
    if manifest.get("project_id") != args.project:
        parser.error("Snapshot project mismatch")
    payload = {"project_id":args.project,"persona_id":"default","cases":cases,
        "sections":json.loads((snapshot/"sections.json").read_text()),
        "source_manifest":manifest,"runtime":(HERE/"readonly_runtime.py").read_text(),
        "history_policy":args.history_policy,
        "history_query_source":(HERE/"history_query.py").read_text(),
        "implementation":Path(__file__).read_text().replace("if __name__ == \"__main__\":", "if False:"),
        "snapshot":str(snapshot),
        "snapshot_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs[1:]}}
    # The container imports only the pure validation/fusion definitions, avoiding
    # any assumption that this worktree is installed in the serving image.
    payload["implementation"] = payload["implementation"].split("BOOTSTRAP = r'''",1)[0].replace("from experiment_io import validate_output", "").replace("from history_query import HISTORY_POLICIES", "")
    result = subprocess.run(
        ["docker","exec","-i","-w","/app","openvman-api-1","python","-c",BOOTSTRAP],
        input=json.dumps(payload,ensure_ascii=False),capture_output=True,text=True,
    )
    if result.returncode:
        raise SystemExit(result.stderr[-5000:])
    data = json.loads(next(line for line in reversed(result.stdout.splitlines()) if line.startswith("{")))
    data["implementation_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    data["runtime_sha256"] = hashlib.sha256(payload["runtime"].encode()).hexdigest()
    data["cases_sha256"] = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(data,ensure_ascii=False,indent=1))
    print(json.dumps({k:data[k] for k in ("project_id","accepted_sections","rejected_sections","readonly_check")},ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Use production multi-turn queries for held-out read-only QA retrieval."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from experiment_io import validate_output


HERE = Path(__file__).resolve().parent
BOOTSTRAP = r'''
import copy
import json
from pathlib import Path
import sys
import types

import lancedb
import numpy as np

payload = json.load(sys.stdin)
runtime = types.ModuleType("readonly_runtime")
sys.modules[runtime.__name__] = runtime
exec(payload["runtime"], runtime.__dict__)
pid = payload["project_id"]
with runtime.readonly_search(pid) as search:
    from config import get_settings
    from core.turn_reads import knowledge_queries, previous_user_text
    from infra.db import resolve_vector_table_name
    from knowledge.doc_meta import list_disabled_document_paths
    from memory.embedder import encode_query_with_fallback, get_embedder
    from tools.search_helpers import merge_search_results

    cfg = get_settings()
    baseline_config = cfg.model_dump(mode="json")
    table = lancedb.connect(f"/data/projects/{pid}/lancedb").open_table(
        resolve_vector_table_name("knowledge")
    )
    raw = [r for r in table.to_arrow().to_pylist() if r.get("text")]
    sections = payload["sections"]
    identity = cfg.resolved_embedding_write_identity
    vectors, spec, _ = get_embedder().encode_with_metadata(
        [s["text"] for s in sections], input_type="document",
        forced_identity=identity, titles=[s["title"] for s in sections],
    )
    if spec.get("identity") != identity:
        raise ValueError("Document identity differs")
    pools = [
        ("original", np.array([r["vector"] for r in raw], dtype=np.float32), raw),
        ("wiki", np.array(vectors, dtype=np.float32), sections),
    ]
    for _, vectors, _ in pools:
        if not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=.005):
            raise ValueError("Non-unit document vectors")
    disabled = sorted(list_disabled_document_paths(pid))
    out = {}

    def vector_hits(query):
        route = encode_query_with_fallback(
            query, project_id=pid, table_names=("knowledge",),
        )
        if cfg.resolve_embedding_identity(route.version) != identity:
            raise ValueError("Query/document model mismatch")
        vector = np.array(route.vector, dtype=np.float32)
        if not np.isclose(np.linalg.norm(vector), 1, atol=.005):
            raise ValueError("Non-unit query vector")
        found = []
        for source, vectors, records in pools:
            distances = ((vectors - vector) ** 2).sum(axis=1)
            for i in np.argsort(distances)[:12]:
                record = records[i]
                path = record.get("path", record.get("slug", ""))
                found.append({
                    "text": record["text"], "path": path,
                    "chunk_id": f"{source}:{record.get('chunk_id', i)}",
                    "src": source, "_distance": float(distances[i]),
                    "metadata": record.get("metadata", ""),
                })
        return sorted(found, key=lambda r: r["_distance"])

    for case in payload["cases"]:
        history = case.get("history", [])
        previous = previous_user_text(history, case["q"])
        queries = knowledge_queries(case["q"], previous)
        variants = {}
        for name, k in (("prod_k3_t068", 3), ("prod_k5_t068", 5)):
            result = search(case["q"], top_k=k, threshold=.68, queries=queries)
            variants[name] = {key: result[key] for key in (
                "results", "related", "queries",
            )}
        ranked = [(query, vector_hits(query)) for query in queries]
        originals = [(query, [r for r in rows if r["src"] == "original"][:5])
                     for query, rows in ranked]
        mixed = [(query, rows[:5]) for query, rows in ranked]
        mixed_hits = merge_search_results(mixed, limit=5)
        variants["vector_multi"] = {
            "results": merge_search_results(originals, limit=5),
            "related": [], "queries": queries,
        }
        variants["mixed_multi"] = {
            "results": mixed_hits, "related": [], "queries": queries,
        }
        variants["mixed_single"] = {
            "results": ranked[0][1][:5], "related": [],
            "queries": [case["q"]],
        }
        # Give original text a comparable character allowance, without clipping
        # a record halfway through a safety condition or a table row.
        budget = sum(len(r["text"]) for r in mixed_hits)
        full_originals = [(query, [r for r in rows if r["src"] == "original"])
                          for query, rows in ranked]
        budget_rows = merge_search_results(full_originals, limit=12)
        chosen, chars = [], 0
        for row in budget_rows:
            if chars >= budget:
                break
            chosen.append(row)
            chars += len(row["text"])
        variants["vector_char_budget"] = {
            "results": chosen, "related": [], "queries": queries,
            "target_chars": budget, "actual_chars": chars,
        }
        out[case["id"]] = variants
    assert cfg.model_dump(mode="json") == baseline_config
print(json.dumps({
    "project_id": pid, "questions": out,
    "table_version": table.version, "record_count": len(raw),
    "disabled_paths": disabled, "readonly_manifest_unchanged": True,
    "formal_query_builder": "core.turn_reads.knowledge_queries",
    "candidate_filter_warning": "Raw-vector variants omit production visibility/language/dedup filters.",
}, ensure_ascii=False))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--sections", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = validate_output(args.output, inputs=[args.cases, args.sections])
    cases = json.loads(args.cases.read_text())
    if not cases or len({c["id"] for c in cases}) != len(cases):
        parser.error("Cases need unique IDs")
    payload = {
        "project_id": args.project, "cases": cases,
        "sections": json.loads(args.sections.read_text()),
        "runtime": (HERE / "readonly_runtime.py").read_text(),
    }
    result = subprocess.run(
        ["docker", "exec", "-i", "-w", "/app", "openvman-api-1",
         "python", "-c", BOOTSTRAP],
        input=json.dumps(payload, ensure_ascii=False), text=True,
        capture_output=True,
    )
    if result.returncode:
        raise SystemExit(result.stderr[-5000:])
    data = json.loads(next(line for line in reversed(result.stdout.splitlines())
                           if line.startswith("{")))
    data["cases_sha256"] = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    data["sections_sha256"] = hashlib.sha256(args.sections.read_bytes()).hexdigest()
    data["runtime_sha256"] = hashlib.sha256(payload["runtime"].encode()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in data.items() if k != "questions"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

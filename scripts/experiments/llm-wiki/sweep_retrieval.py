"""Run production retrieval variants in an isolated, read-only container process."""

import argparse
import json
from pathlib import Path
import subprocess

from experiment_io import validate_output


HERE = Path(__file__).resolve().parent
VARIANTS = {
    "prod_k3_t068": (3, 0.68),
    "prod_k5_t068": (5, 0.68),
    "prod_k5_t065": (5, 0.65),
    "prod_k5_t060": (5, 0.60),
}

CONTAINER_SCRIPT = r'''
import hashlib
import json
from pathlib import Path
import sys
import time
import types

import numpy as np

payload = json.load(sys.stdin)
runtime = types.ModuleType("readonly_runtime")
sys.modules[runtime.__name__] = runtime
exec(payload["runtime"], runtime.__dict__)

def snapshot(root):
    # Include database versions, knowledge files and session/trace files.
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in root.rglob("*") if p.is_file()
    }

pid = payload["project_id"]
root = Path("/data/projects") / pid
before = snapshot(root)
out = {}
with runtime.readonly_search(pid) as search:
    from config import get_settings
    from infra.db import resolve_vector_table_name
    from memory.embedder import encode_query_with_fallback, get_embedder
    import lancedb

    conn = lancedb.connect(str(root / "lancedb"))
    table = conn.open_table(resolve_vector_table_name("knowledge"))
    records = table.to_arrow().to_pylist()
    sections = payload.get("sections", [])
    if sections:
        identity = get_settings().resolved_embedding_write_identity
        vectors, document_spec, _ = get_embedder().encode_with_metadata(
            [s["text"] for s in sections], input_type="document",
            forced_identity=identity,
            titles=[s["title"] for s in sections],
        )
        if document_spec.get("identity") != identity:
            raise ValueError("Unexpected document embedding identity")
        wiki_vectors = np.array(vectors, dtype=np.float32)
        qa_records = [r for r in records if r.get("text")]
        qa_vectors = np.array([r["vector"] for r in qa_records], dtype=np.float32)
        for pool in (wiki_vectors, qa_vectors):
            if not np.allclose(np.linalg.norm(pool, axis=1), 1, atol=0.005):
                raise ValueError("Cosine comparison requires unit document vectors")

    for question in payload["questions"]:
        variants = {}
        for name, (k, threshold) in payload["variants"].items():
            start = time.perf_counter()
            result = search(question["q"], top_k=k, threshold=threshold)
            variants[name] = {
                "results": result["results"], "related": result["related"],
                "queries": result["queries"],
                "retrieval_ms": round((time.perf_counter() - start) * 1000, 2),
            }
        if sections:
            route = encode_query_with_fallback(
                question["q"], project_id=pid, table_names=("knowledge",),
            )
            query = np.array(route.vector, dtype=np.float32)
            # Query/document semantics differ intentionally for asymmetric embedding.
            if get_settings().resolve_embedding_identity(route.version) != identity:
                raise ValueError("Mixed-vector query and document identities differ")
            if not np.isclose(np.linalg.norm(query), 1, atol=0.005):
                raise ValueError("Cosine comparison requires a unit query vector")
            candidates = []
            for source, vectors, items in (
                ("qa", qa_vectors, qa_records),
                ("wiki", wiki_vectors, sections),
            ):
                distances = ((vectors - query) ** 2).sum(axis=1)
                for index in np.argsort(distances)[:5]:
                    item = items[index]
                    candidates.append({
                        "src": source, "text": item["text"],
                        "path": item.get("path", item.get("slug", "")),
                        "cos": float(1 - distances[index] / 2),
                        "distance": float(distances[index]),
                    })
            # Match the previous experiment's C; this does not emulate hybrid RAG.
            mixed = sorted(candidates, key=lambda r: r["distance"])[:5]
            variants["vector_only"] = {
                "results": [r for r in candidates if r["src"] == "qa"],
                "related": [],
            }
            variants["mixed_vector"] = {"results": mixed, "related": []}
        out[question["id"]] = variants

after = snapshot(root)
changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
print(json.dumps({
    "project_id": pid, "variants": payload["variants"], "questions": out,
    "readonly_check": {"file_count": len(before), "changed_paths": changed},
    "runtime_sha256": hashlib.sha256(payload["runtime"].encode()).hexdigest(),
    "table_version": table.version, "record_count": len(records),
}, ensure_ascii=False))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sections", type=Path)
    parser.add_argument("--container", default="openvman-api-1")
    args = parser.parse_args()
    try:
        args.output = validate_output(args.output, inputs=[
            p for p in (args.questions, args.sections) if p is not None
        ])
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    questions = json.loads(args.questions.read_text())
    if len({q["id"] for q in questions}) != len(questions):
        parser.error("question IDs must be unique")
    payload = {
        "project_id": args.project,
        "questions": questions,
        "variants": VARIANTS,
        "runtime": (HERE / "readonly_runtime.py").read_text(),
    }
    if args.sections:
        payload["sections"] = json.loads(args.sections.read_text())
    result = subprocess.run(
        ["docker", "exec", "-i", "-w", "/app", args.container,
         "python", "-c", CONTAINER_SCRIPT],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True, text=True,
    )
    if result.returncode:
        raise SystemExit(result.stderr[-4000:])
    data = json.loads(next(
        line for line in reversed(result.stdout.splitlines())
        if line.startswith("{")
    ))
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    if data["readonly_check"]["changed_paths"]:
        raise SystemExit("Project files changed during run; inspect readonly_check")
    print(json.dumps({k: data[k] for k in (
        "project_id", "readonly_check", "table_version", "record_count",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()

import json, sys
sys.path.insert(0, "/app")
import memory.retrieval as retrieval
retrieval.record_trace = lambda *a, **k: None
from config import get_settings
from memory.embedder import encode_query_with_fallback
P = "dev-c0c8fdff34"
qs = [q for q in json.load(open("/tmp/search_queries.json")) if q["set"] in ("kb", "xl", "asr")]
routes = [encode_query_with_fallback(q["q"], project_id=P, table_names=("knowledge",)) for q in qs]
cfg = get_settings()
for ret, fts in [(0.66, 0.62), (0.68, 0.63), (0.70, 0.65), (0.72, 0.67), (0.70, 0.60), (0.68, 0.60)]:
    object.__setattr__(cfg, "embedding_thresholds", json.dumps({"gemma": {"retrieval": ret, "retrieval_fts": fts}}))
    hit = {}; noise = 0; empty = 0
    for q, route in zip(qs, routes):
        rows = retrieval.search_records("knowledge", route.vector, top_k=5, query_text=q["q"], query_type="hybrid",
                                        project_id=P, embedding_version=route.version, language=q.get("lang"))
        if q["expect"] is None: noise += len(rows); continue
        keys = q["expect"].split("|")
        ok = any(any(k in r.get("text", "") for k in keys) for r in rows[:3]); empty += not rows
        h = hit.setdefault(q["set"], [0, 0]); h[0] += ok; h[1] += 1
    print(f"retrieval {ret} fts {fts}: " + "  ".join(f"{k} {a}/{b}" for k, (a, b) in sorted(hit.items())) + f"  noise {noise}/45  empty-results {empty}")

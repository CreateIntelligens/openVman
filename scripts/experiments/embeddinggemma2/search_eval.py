import json, sys, time
sys.path.insert(0, "/app")
import memory.retrieval as retrieval
retrieval.record_trace = lambda *a, **k: None
from memory.embedder import encode_query_with_fallback
P = "dev-c0c8fdff34"
qs = json.load(open("/tmp/search_queries.json"))
out = []
for q in qs:
    t = time.perf_counter()
    route = encode_query_with_fallback(q["q"], project_id=P, table_names=("knowledge",))
    rows = retrieval.search_records("knowledge", route.vector, top_k=5, query_text=q["q"], query_type="hybrid",
                                    project_id=P, embedding_version=route.version, language=q.get("lang"))
    out.append({**q, "version": route.version.split(":")[0], "ms": round((time.perf_counter() - t) * 1000),
                "rows": [{"text": r.get("text", ""), "path": r.get("path", ""), "distance": r.get("_distance")} for r in rows]})
json.dump(out, open("/tmp/search_out.json", "w"), ensure_ascii=False)
print(len(out), "done", sorted({o["version"] for o in out}))

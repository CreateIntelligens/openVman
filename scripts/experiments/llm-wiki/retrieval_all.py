"""在 openvman-api-1 容器內執行，唯讀：stdin 給 sections、pages、questions，stdout 印 JSON。"""
import json
import sys
import types

import lancedb
import numpy as np

from config import get_settings
from infra.db import resolve_vector_table_name
from memory.embedder import get_embedder

payload = json.load(sys.stdin)


def retrieve(payload, search):
    from memory.embedder import encode_query_with_fallback

    pid = payload["project_id"]
    recs = [r for r in lancedb.connect(f"/data/projects/{pid}/lancedb").open_table(resolve_vector_table_name("knowledge")).to_arrow().to_pylist() if r.get("text")]
    qa_vec = np.array([r["vector"] for r in recs], dtype=np.float32)
    identity = get_settings().resolved_embedding_write_identity
    secs = payload["sections"]
    kw = {p["slug"]: "、".join(p["keywords"]) for p in payload["pages"]}

    def embed(texts, titles):
        vecs, _, _ = get_embedder().encode_with_metadata(texts, input_type="document", forced_identity=identity, titles=titles)
        return np.array(vecs, dtype=np.float32)

    titles = [s["title"] for s in secs]
    wiki_vec = embed([s["text"] for s in secs], titles)
    wiki_kw_vec = embed([s["text"] + "\n關鍵詞：" + kw[s["slug"]] for s in secs], titles)

    def top(vec, qv, items, k=5):
        # LanceDB 用 L2 平方；單位向量時 cosine = 1 - d/2。
        d = ((vec - qv) ** 2).sum(axis=1)
        return [{**items(i), "d": float(d[i]), "cos": float(1 - d[i] / 2)} for i in np.argsort(d)[:k]]

    qa_item = lambda i: {"src": "qa", "path": recs[i]["path"], "text": recs[i]["text"]}
    wiki_item = lambda i: {"src": "wiki", "path": secs[i]["slug"] + " > " + secs[i]["heading"], "text": secs[i]["text"]}
    out = {}
    for q in payload["questions"]:
        qv = np.array(encode_query_with_fallback(q["q"], project_id=pid, table_names=("knowledge",)).vector, dtype=np.float32)
        prod = search(
            q["q"], top_k=3,
            threshold=get_settings().similarity_thresholds(identity).retrieval,
        )
        qa = top(qa_vec, qv, qa_item)
        out[q["id"]] = {
            "a_prod": [{"src": "qa", "path": r.get("path"), "text": r.get("text")} for r in prod["results"]],
            "a_prod_related": [{"src": "graph", "path": r.get("path"), "text": r.get("text")} for r in prod["related"]],
            "a_vec": qa,
            "c": sorted(qa + top(wiki_vec, qv, wiki_item), key=lambda x: x["d"])[:5],
            "c_kw": sorted(qa + top(wiki_kw_vec, qv, wiki_item), key=lambda x: x["d"])[:5],
        }
    return out


runtime = types.ModuleType("readonly_runtime")
sys.modules[runtime.__name__] = runtime
exec(payload["runtime"], runtime.__dict__)
with runtime.readonly_search(payload["project_id"]) as search:
    out = retrieve(payload, search)
print(json.dumps(out, ensure_ascii=False))

"""比較 knowledge 表的全文索引斷詞：simple（現行）與 ngram。

在 api 容器內執行。把鶴記dev 的 knowledge 表複製到 /tmp 的 LanceDB，各建一種
全文索引，用同一組查詢跑 hybrid 檢索，看預期段落有沒有進前 5 名。不寫入專案資料。
"""

import json
import re
import sys
import time

sys.path.insert(0, "/app")

import lancedb

import memory.retrieval as retrieval
from infra.db import get_knowledge_table
from memory.embedder import encode_query_with_fallback

P = "dev-c0c8fdff34"
VARIANTS = {
    "simple": {},
    "ngram23": {"base_tokenizer": "ngram", "ngram_min_length": 2, "ngram_max_length": 3},
    "ngram24": {"base_tokenizer": "ngram", "ngram_min_length": 2, "ngram_max_length": 4},
}

queries = json.load(open(sys.argv[1]))
first = encode_query_with_fallback(queries[0]["q"], project_id=P, table_names=("knowledge",))
source = get_knowledge_table(P, first.version).to_arrow()
db = lancedb.connect("/tmp/fts-ngram-db")
tables = {}
for name, opts in VARIANTS.items():
    table = db.create_table(name, data=source, mode="overwrite")
    table.create_fts_index("text", replace=True, **opts)
    tables[name] = table

vectors = {q["q"]: encode_query_with_fallback(q["q"], project_id=P, table_names=("knowledge",)).vector for q in queries}
out = []
for q in [q for q in queries if q.get("expect")]:
    row = {**q}
    for name, table in tables.items():
        t = time.perf_counter()
        hits = retrieval._hybrid_search(table, vectors[q["q"]], q["q"], 5, 60, [], first.version, {})
        row[name] = {
            "ms": round((time.perf_counter() - t) * 1000, 1),
            "hit": any(re.search(q["expect"], (h.get("text") or "") + (h.get("path") or ""), re.I) for h in hits),
            "top": [(h.get("text") or "")[:80].replace("\n", " ") for h in hits[:3]],
        }
    out.append(row)
json.dump(out, open("/tmp/fts_ngram_out.json", "w"), ensure_ascii=False, indent=1)
for name in VARIANTS:
    hits = sum(r[name]["hit"] for r in out)
    ms = sorted(r[name]["ms"] for r in out)[len(out) // 2]
    print(f"{name}: {hits}/{len(out)} p50 {ms} ms")

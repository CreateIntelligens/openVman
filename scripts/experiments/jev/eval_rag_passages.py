"""Offline check: can Jev screen retrieved knowledge passages without losing the answer?

Runs inside the Brain container against a real project's knowledge table (read-only).
For each EVAK QA question: retrieve top-k passages, mark "gold" passages (contain the
reference answer or the question itself), ask Jev per passage whether it is on-topic
and whether it can back a direct answer, all in one call per question.

    python eval_rag_passages.py <qa.csv> <project_id> [top_k]
"""

import csv
import json
import re
import statistics
import sys
import time

from tools.builtin.knowledge_tools import _search_one

try:
    from core.jev_client import jev_nouls
except ImportError:  # 容器裡是還沒部署的舊版：從 JEV_CLIENT_PATH 載入新版
    import importlib.util
    import os

    _spec = importlib.util.spec_from_file_location("jev_client_new", os.environ["JEV_CLIENT_PATH"])
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    jev_nouls = _module.jev_nouls

RELEVANT = {
    "instructions": "段落 {pid} 是否談到使用者問題（query）所問的主題或產品？",
    "criteria": {"true": "段落內容與問題的主題、產品或型號直接相關",
                 "false": "段落談的是別的主題或別的產品，只是字面相近"},
}
EVIDENCE = {
    "instructions": "段落 {pid} 是否包含能直接回答使用者問題（query）的資訊？",
    "criteria": {"true": "段落裡有問題要的數值、型號、條件或步驟，可以直接拿來回答",
                 "false": "段落沒有問題要的具體資訊，或只沾到邊"},
}


def norm(text):
    return re.sub(r"\s+", "", text or "")


def question(template, pid):
    return {"instructions": template["instructions"].format(pid=pid),
            "criteria": template["criteria"]}


def main():
    rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
    project = sys.argv[2]
    top_k = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    out, latencies = [], []
    for row in rows:
        q, a = row["q"].strip(), row["a"].strip()
        passages, _, _ = _search_one("knowledge", q, top_k, "default", project)
        items = []
        for i, p in enumerate(passages, 1):
            text = str(p.get("text") or p.get("content") or "")
            gold = norm(a)[:24] in norm(text) or norm(q)[:24] in norm(text)
            items.append({"pid": f"p{i}", "text": text[:1500], "gold": gold})
        if not items:
            continue
        state = json.dumps({"query": q, "passages": [{"id": it["pid"], "text": it["text"]} for it in items]},
                           ensure_ascii=False)
        questions = {}
        for it in items:
            questions[f"{it['pid']}_rel"] = question(RELEVANT, it["pid"])
            questions[f"{it['pid']}_evd"] = question(EVIDENCE, it["pid"])
        started = time.perf_counter()
        scores = jev_nouls(state, questions, timeout=15)
        latencies.append((time.perf_counter() - started) * 1000)
        for it in items:
            it["rel"], it["evd"] = scores[f"{it['pid']}_rel"], scores[f"{it['pid']}_evd"]
            del it["text"]
        out.append({"index": row["index"], "items": items})

    all_items = [it for r in out for it in r["items"]]
    gold = [it for it in all_items if it["gold"]]
    other = [it for it in all_items if not it["gold"]]
    with_gold = [r for r in out if any(it["gold"] for it in r["items"])]
    print(f"questions={len(out)} with_gold={len(with_gold)} passages={len(all_items)} gold={len(gold)}")
    for th in (0.2, 0.3, 0.45):
        kept_gold = sum(it["rel"] >= th for it in gold)
        dropped_other = sum(it["rel"] < th for it in other)
        q_lost = sum(not any(it["gold"] and it["rel"] >= th for it in r["items"]) for r in with_gold)
        print(f"relevance>={th}: gold kept {kept_gold}/{len(gold)}  non-gold dropped {dropped_other}/{len(other)}"
              f"  questions losing all gold {q_lost}/{len(with_gold)}")
    ev_gold = sum(it["evd"] >= 0.5 for it in gold)
    ev_other = sum(it["evd"] >= 0.5 for it in other)
    print(f"evidence>=0.5: gold {ev_gold}/{len(gold)}  non-gold {ev_other}/{len(other)}")
    latencies.sort()
    print(f"latency p50={latencies[len(latencies)//2]:.0f}ms p95={latencies[int(len(latencies)*.95)-1]:.0f}ms")
    json.dump(out, open("/tmp/rag_eval.json", "w"), ensure_ascii=False)


if __name__ == "__main__":
    main()

"""A/B the knowledge-passage screen end to end through /brain/chat.

Runs inside the Brain container. Asks EVAK questions for real, records response time
and how many key facts (numbers / model codes) of the reference answer appear in the
reply. Run once with RAG_JEV_SCREEN_ENABLED off and once on, then compare.

    python ab_rag_screen.py <qa.csv> <project_id> <label> [n]
"""

import csv
import json
import re
import sys
import time
import urllib.request

from config import get_settings

FACT = re.compile(r"[A-Za-z0-9][A-Za-z0-9.()/-]*\d[A-Za-z0-9.()/-]*|\d+(?:\.\d+)?")


def key_facts(answer: str) -> set[str]:
    return {m.group(0).strip(".()") for m in FACT.finditer(answer) if len(m.group(0)) >= 2}


def main():
    rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
    project, label = sys.argv[2], sys.argv[3]
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 15
    token = get_settings().gateway_internal_token
    results = []
    for row in rows[:n]:
        body = json.dumps({
            "message": row["q"], "project_id": project, "mode": "fast",
            "session_id": f"ragab-{label}-{row['index']}",
        }).encode()
        req = urllib.request.Request("http://127.0.0.1:8100/brain/chat", data=body, headers={
            "Content-Type": "application/json", "X-Internal-Token": token,
            "X-OpenVMan-User-ID": "ragab", "X-OpenVMan-Role": "admin",
            "X-OpenVMan-Project-ID": project,
        })
        started = time.perf_counter()
        try:
            reply = json.loads(urllib.request.urlopen(req, timeout=120).read()).get("reply", "")
            error = ""
        except Exception as exc:  # noqa: BLE001
            reply, error = "", type(exc).__name__
        seconds = time.perf_counter() - started
        facts = key_facts(row["a"])
        hit = sum(f in reply.replace(" ", "") for f in facts)
        results.append({"index": row["index"], "seconds": round(seconds, 2), "facts": len(facts),
                        "hit": hit, "error": error, "reply": reply[:300]})
        print(json.dumps(results[-1], ensure_ascii=False)[:200], flush=True)
        time.sleep(1)
    ok = [r for r in results if not r["error"]]
    secs = sorted(r["seconds"] for r in ok)
    total_facts = sum(r["facts"] for r in ok)
    print(json.dumps({
        "label": label, "n": len(results), "errors": len(results) - len(ok),
        "p50_s": secs[len(secs) // 2] if secs else None,
        "mean_s": round(sum(secs) / len(secs), 2) if secs else None,
        "fact_recall": round(sum(r["hit"] for r in ok) / total_facts, 3) if total_facts else None,
    }, ensure_ascii=False))
    json.dump(results, open(f"/tmp/ragab_{label}.json", "w"), ensure_ascii=False)


if __name__ == "__main__":
    main()

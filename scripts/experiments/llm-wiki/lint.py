import collections
import concurrent.futures as cf
import json
import os
import re
import sys

import llm

rows = json.load(open("rows_planted.json"))
IDS = {f"{r['file']}#{r['index']}" for r in rows}

def topic(f):
    t = re.sub(r"\.csv$", "", f)
    t = re.sub(r"_IMG.*$|_qa_\d+$", "", t)
    return t

def fmt(r):
    a = re.sub(r"\s+", " ", r["a"])
    return f"[{r['file']}#{r['index']}] Q: {r['q']} A: {a}"

PROMPT = """你是醫院衛教知識庫的稽核員。下面是知識庫的 QA 條目，每條前面的 [檔名#編號] 是它的 ID。
請找出會讓虛擬助理答錯或答不清楚的問題，只回報有條目原文為據的問題，不要憑常識補充醫學意見。

問題類型：
- contradiction：兩條以上條目對同一件事（時間、價格、電話、人名、數字、做法建議）說法互相衝突
- duplicate：不同條目問同一件事、答案重複或不一致，應合併
- ambiguous_question：問題本身沒有主詞，單看問題看不出在問哪個疾病或科別（例如只寫「如何預防」）
- privacy：去識別化資料中仍出現疑似真實人名或個資
- incomplete：答案沒有實質內容，只叫使用者去看圖、掃 QR code、加 LINE

輸出 JSON：{{"findings": [{{"type": "...", "ids": ["檔名#編號", ...], "summary": "60 字內說明", "evidence": "引用條目中的關鍵字句，各 30 字內"}}]}}
ids 只能用下面出現過的 ID。

{scope}
條目：
{rows}
"""

def run(name, groups):
    def one(item):
        label, rs = item
        out = llm.gen(PROMPT.format(scope=f"範圍：{label}", rows="\n".join(fmt(r) for r in rs)))
        fs = out.get("findings", []) if isinstance(out, dict) else []
        for f in fs: f["group"] = label
        return fs
    with cf.ThreadPoolExecutor(6) as ex:
        findings = [f for fs in ex.map(one, groups) for f in fs]
    bad = sum(1 for f in findings for i in f.get("ids", []) if i not in IDS)
    json.dump(findings, open(f"lint_{name}{os.environ.get('TAG', '')}.json", "w"), ensure_ascii=False, indent=1)
    c = collections.Counter(f.get("type") for f in findings)
    print(name, "groups", len(groups), "findings", len(findings), dict(c), "invalid ids", bad, "usage", llm.USAGE)

by = collections.defaultdict(list)
for r in rows: by[topic(r["file"])].append(r)
ops = [r for r in rows if not re.match(r"^\d+-", r["file"])]
mode = sys.argv[1] if __name__ == "__main__" else ""
if mode == "whole":
    run("whole", [("整個知識庫", rows)])
elif mode == "grouped":
    groups = [(f"主題：{k}", v) for k, v in sorted(by.items())]
    groups.append(("跨檔案：醫院營運資訊（門診、時間表、科別、健檢、復健、聯絡方式）", ops))
    run("grouped", groups)

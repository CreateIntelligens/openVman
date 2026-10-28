"""七種檢索／編譯做法 × 兩輪，作答用 flash-lite、判分用 3.8-flash。

在產出目錄執行：cd ~/openvman-experiments/llm-wiki && python3 <本目錄>/ab3.py
"""
import collections
import concurrent.futures as cf
import json
import pathlib
import re

import llm

HERE = pathlib.Path(__file__).resolve().parent
ANSWER_MODEL = "gemini-3.5-flash-lite"
JUDGE_MODEL = "gemini-3.8-flash"
THRESHOLD = 0.68  # memory/thresholds.py 的 gemma retrieval 門檻
REPS = 2

qs = json.load(open(HERE / "questions.json"))
ret = json.load(open("retrieval_all.json"))
pages = {p["slug"]: p for p in json.load(open("wiki/pages.json"))}
index = open("wiki/index.md").read()

ANSWER = """你是醫院的衛教虛擬助理，用口語、簡短的繁體中文回答民眾。
只能根據下面的參考資料回答；資料沒有提到的，就說目前查不到，建議洽詢醫院，不要自己推測或補充。
不要念出資料裡的方括號出處。

參考資料：
{ctx}

民眾問題：{q}
"""
ROUTE = """下面是醫院知識庫的頁面目錄。請選出回答這個問題需要讀的頁面，最多 3 頁；目錄裡沒有相關頁面就回傳空陣列。
輸出 JSON：{{"pages": ["檔名.md", ...]}}

{index}

問題：{q}
"""
JUDGE_ANSWERABLE = """你是評分員。根據標準答案評分虛擬助理的回答。補充正確、不誤導的細節不扣分。
correct（涵蓋標準答案要點且沒有錯誤資訊）、partial（只答對部分要點）、wrong（答錯、答非所問，或說查不到）
輸出 JSON：{{"label": "...", "reason": "40 字內"}}

問題：{q}
標準答案：{gold}
助理回答：{a}
"""
JUDGE_REFUSAL = """你是評分員。這題知識庫沒有完整答案，標準答案說明了助理可以說什麼、不可以說什麼。
refused（說查不到、資料沒有列出、建議洽詢，且沒有編造標準答案禁止的具體資訊）、hallucinated（給出標準答案禁止的具體數字、時段、肯定或否定結論）
輸出 JSON：{{"label": "...", "reason": "40 字內"}}

問題：{q}
標準答案：{gold}
助理回答：{a}
"""

def ctx_of(items):
    return "\n\n".join(x["text"] for x in items) or "（沒有找到資料）"

def answer(q, ctx):
    return llm.gen(ANSWER.format(ctx=ctx, q=q["q"]), json_mode=False, model=ANSWER_MODEL).strip()

def wiki_route(q):
    chosen = llm.gen(ROUTE.format(index=index, q=q["q"]), model=ANSWER_MODEL).get("pages", [])[:3]
    slugs = [s for s in (re.sub(r"\.md$", "", c) for c in chosen) if s in pages]
    return "\n\n".join(f"# {pages[s]['title']}\n" + open(f"wiki/{s}.md").read() for s in slugs) or "（沒有找到資料）", slugs

def thresh(items):
    return [x for x in items if x["cos"] >= THRESHOLD]

VARIANTS = {
    "A_prod": lambda q, r: (ctx_of(r["a_prod"] + r["a_prod_related"]), []),
    "A2_vector": lambda q, r: (ctx_of(r["a_vec"]), []),
    "B_wiki_route": lambda q, r: wiki_route(q),
    "C": lambda q, r: (ctx_of(r["c"]), []),
    "C_thresh": lambda q, r: (ctx_of(thresh(r["c"])), []),
    "C_kw": lambda q, r: (ctx_of(r["c_kw"]), []),
    "C_kw_thresh": lambda q, r: (ctx_of(thresh(r["c_kw"])), []),
}

def run(job):
    rep, q, name = job
    ctx, slugs = VARIANTS[name](q, ret[q["id"]])
    a = answer(q, ctx)
    tmpl = JUDGE_ANSWERABLE if q["rows"] else JUDGE_REFUSAL
    j = llm.gen(tmpl.format(q=q["q"], gold=q["gold"], a=a), model=JUDGE_MODEL)
    return {"rep": rep, "id": q["id"], "bucket": q["bucket"], "variant": name, "pages": slugs, "answer": a, "label": j.get("label"), "reason": j.get("reason")}

jobs = [(rep, q, name) for rep in range(REPS) for q in qs for name in VARIANTS]
with cf.ThreadPoolExecutor(8) as ex:
    res = list(ex.map(run, jobs))
json.dump(res, open("ab3_results.json", "w"), ensure_ascii=False, indent=1)

buckets = ["direct", "paraphrase", "aggregate", "unanswerable", "near_miss"]
print("variant".ljust(13), "rep", " ".join(b[:10].ljust(18) for b in buckets))
for name in VARIANTS:
    for rep in range(REPS):
        cells = []
        for b in buckets:
            c = collections.Counter(x["label"] for x in res if x["variant"] == name and x["rep"] == rep and x["bucket"] == b)
            cells.append(" ".join(f"{k[:4]}{v}" for k, v in sorted(c.items())).ljust(18))
        print(name.ljust(13), rep, " ".join(cells))
print("usage", llm.USAGE)

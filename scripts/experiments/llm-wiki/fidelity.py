import collections
import concurrent.futures as cf
import glob
import json
import re

import llm

rows = {f"{r['file']}#{r['index']}": r for r in json.load(open("rows.json"))}
CITE = re.compile(r"\[([^\[\]]+?\.csv#\d+(?:\s*[,，、]\s*[^\[\]]+?\.csv#\d+)*)\]")

claims = []
for path in sorted(glob.glob("wiki/*.md")):
    if path.endswith("index.md"): continue
    for line in open(path):
        text = line.strip()
        if not text or text.startswith("#") or text == "---": continue
        refs = [x.strip() for m in CITE.findall(text) for x in re.split(r"[,，、]", m)]
        claims.append({"page": path, "text": text, "refs": refs})

JUDGE = """判斷下面這句 wiki 內容是否被引用的原始條目支持。
- supported：句子的每個事實都能在引用條目找到，數字、時間、人名一致
- partial：大致正確但有遺漏條件、過度概括，或加了條目沒寫的細節
- unsupported：有事實與引用條目矛盾，或引用條目完全沒提到
輸出 JSON：{{"label": "supported|partial|unsupported", "reason": "30 字內"}}

wiki 句子：{text}

引用條目：
{src}
"""

def judge(c):
    srcs = [rows[r] for r in c["refs"] if r in rows]
    c["bad_refs"] = [r for r in c["refs"] if r not in rows]
    if not c["refs"]:
        c["label"], c["reason"] = "no_citation", ""
        return c
    if not srcs:
        c["label"], c["reason"] = "bad_citation", ""
        return c
    out = llm.gen(JUDGE.format(text=c["text"], src="\n".join(f"[{r['file']}#{r['index']}] Q: {r['q']} A: {r['a']}" for r in srcs)))
    c["label"], c["reason"] = out.get("label"), out.get("reason", "")
    return c

with cf.ThreadPoolExecutor(8) as ex:
    claims = list(ex.map(judge, claims))
json.dump(claims, open("fidelity.json", "w"), ensure_ascii=False, indent=1)
print(len(claims), dict(collections.Counter(c["label"] for c in claims)), "usage", llm.USAGE)

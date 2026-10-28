import collections
import concurrent.futures as cf
import json
import re

import llm
from facts import COMPARE

facts = json.load(open("facts.json"))
names = sorted({re.sub(r"^創造智能醫院", "", f["entity"]) or "醫院" for f in facts})
CANON = """下面是醫院知識庫裡出現的單位名稱，同一個單位可能有不同寫法（例如「復健科」「復健治療中心」「復健中心」可能指同一處，也可能不同）。
請把每個名稱對應到一個標準單位名稱；指的是醫院整體就對應到「醫院」。只有確定是同一處才合併。
輸出 JSON：{{"map": {{"原名稱": "標準名稱", ...}}}}

名稱：
{names}
"""
mapping = llm.gen(CANON.format(names="\n".join(names)))["map"]
for f in facts:
    raw = re.sub(r"^創造智能醫院", "", f["entity"]) or "醫院"
    f["canon"] = mapping.get(raw, raw)
groups = collections.defaultdict(list)
for f in facts: groups[f["canon"]].append(f)
# 醫院整體的規定（報到、電話）也適用各單位，所以「醫院」組的事實併進每一組比對。
hospital = groups.get("醫院", [])
items = [(k, v + ([] if k == "醫院" else hospital)) for k, v in groups.items() if len(v) + len(hospital) > 1]
def one(item):
    k, fs = item
    lines = "\n".join(f"{f['id']} | {f['canon']} | {f['attribute']} | {f['value']}" for f in fs)
    out = llm.gen(COMPARE.format(facts=lines)).get("findings", [])
    for o in out: o["group"] = k
    return out
with cf.ThreadPoolExecutor(6) as ex:
    found = [o for out in ex.map(one, items) for o in out]
json.dump({"map": mapping, "findings": found}, open("lint_facts2.json", "w"), ensure_ascii=False, indent=1)
print("canonical units", len(groups), "groups compared", len(items), "findings", len(found), "usage", llm.USAGE)

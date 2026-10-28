import concurrent.futures as cf
import json
import re

import llm
from lint import fmt, ops, IDS

EXTRACT = """把下面每條醫院 QA 條目拆成原子事實。每個事實是一個「單位／對象」的一個「屬性」的值。
單位例：骨科、復健科、健康管理中心、復健中心、醫院、某位醫師。屬性例：上午門診時段、報到截止、預約電話、主治醫師名單、某天看診醫師、費用、地址、受理時間。
只抽條目裡明寫的事實，值保留原文寫法。
輸出 JSON：{{"facts": [{{"id": "檔名#編號", "entity": "...", "attribute": "...", "value": "..."}}]}}

條目：
{rows}
"""

COMPARE = """下面是從醫院知識庫抽出的事實清單，每行是 id | 單位 | 屬性 | 值。
找出同一個單位、同一件事卻出現互相衝突值的情況，例如同一時段寫成不同時間、同一支電話寫成不同號碼、醫師名單和排班表對不起來、截止時間不一致。
注意：不同時段、不同對象、不同情境的值不算衝突。每個衝突要指出所有相關 id。
輸出 JSON：{{"findings": [{{"type": "contradiction", "ids": ["..."], "summary": "60 字內說明"}}]}}

事實：
{facts}
"""

def main():
    batches = [ops[i:i + 25] for i in range(0, len(ops), 25)]
    with cf.ThreadPoolExecutor(6) as ex:
        outs = list(ex.map(lambda b: llm.gen(EXTRACT.format(rows="\n".join(fmt(r) for r in b))), batches))
    facts = [f for o in outs for f in o.get("facts", []) if f.get("id") in IDS and {"entity", "attribute", "value"} <= f.keys()]
    facts.sort(key=lambda f: (f["entity"], f["attribute"]))
    json.dump(facts, open("facts.json", "w"), ensure_ascii=False, indent=0)
    lines = "\n".join(f"{f['id']} | {f['entity']} | {f['attribute']} | {f['value']}" for f in facts)
    found = llm.gen(COMPARE.format(facts=lines)).get("findings", [])
    json.dump(found, open("lint_facts.json", "w"), ensure_ascii=False, indent=1)
    print("ops rows", len(ops), "facts", len(facts), "findings", len(found), "usage", llm.USAGE)


if __name__ == "__main__":
    main()

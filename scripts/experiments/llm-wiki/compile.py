import collections
import concurrent.futures as cf
import json
import os
import re

import llm

rows = json.load(open("rows.json"))

def topic(f):
    return re.sub(r"_IMG.*$|_qa_\d+$", "", re.sub(r"\.csv$", "", f))

def fmt(r):
    return f"[{r['file']}#{r['index']}] Q: {r['q']} A: {re.sub(r'\s+', ' ', r['a'])}"

PROMPT = """你要把醫院衛教知識庫裡同一主題的 QA 條目，整理成一頁給虛擬助理查閱的 wiki 頁。
規則：
- 只能使用條目內容，不要加入條目沒寫的醫學知識或推論。
- 時間、價格、電話、人名、數字照原文抄。
- 依內容分成小節（例如：是什麼、症狀、原因、檢查、治療、居家照護、何時就醫、費用、時段），重複的資訊合併成一句。
- 每一句或每個條列項目結尾都要用 [檔名#編號] 標出依據，可以標多個。
- 條目彼此說法不一致時，兩種說法都寫，註明「知識庫說法不一」並各自標出處。
- 只叫人掃 QR code、加 LINE、看官網的內容，寫成一句「詳細資訊請參考官方管道」並標出處。

輸出 JSON：{{"title": "頁面標題", "summary": "一句話說明這頁涵蓋什麼（給目錄用，40 字內）", "keywords": ["使用者可能會用的說法，含口語、俗稱，8 到 15 個"], "markdown": "整頁 markdown 內容"}}

主題：{topic}
條目：
{rows}
"""

def main():
    by = collections.defaultdict(list)
    for r in rows: by[topic(r["file"])].append(r)
    os.makedirs("wiki", exist_ok=True)
    def one(item):
        name, rs = item
        out = llm.gen(PROMPT.format(topic=name, rows="\n".join(fmt(r) for r in rs)))
        out["slug"] = re.sub(r"[^\w一-鿿-]+", "_", name)
        out["source_rows"] = len(rs)
        open(f"wiki/{out['slug']}.md", "w").write(out["markdown"])
        return out
    with cf.ThreadPoolExecutor(6) as ex:
        pages = list(ex.map(one, sorted(by.items())))
    index = "\n".join(f"- [{p['title']}]({p['slug']}.md)：{p['summary']}（關鍵詞：{'、'.join(p['keywords'])}）" for p in pages)
    open("wiki/index.md", "w").write("# 知識庫目錄\n\n" + index + "\n")
    json.dump([{k: p[k] for k in ("slug", "title", "summary", "keywords", "source_rows")} for p in pages], open("wiki/pages.json", "w"), ensure_ascii=False, indent=1)
    print("pages", len(pages), "usage", llm.USAGE)

if __name__ == "__main__":
    main()

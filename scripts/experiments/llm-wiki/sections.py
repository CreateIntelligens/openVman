"""把 wiki/*.md 依標題切成小節（去掉出處標記），寫成 wiki_sections.json。"""
import json
import re

CITE = re.compile(r"\s*\[[^\[\]]*?\.csv#\d+[^\[\]]*\]")
pages = {p["slug"]: p for p in json.load(open("wiki/pages.json"))}
secs = []
for slug, page in pages.items():
    heads, buf = [], []

    def flush():
        body = CITE.sub("", "\n".join(buf)).strip()
        if body:
            path = " > ".join(heads)
            secs.append({"slug": slug, "title": page["title"], "heading": path, "text": f"主題：{page['title']}\n{path}\n{body}"})

    for line in open(f"wiki/{slug}.md").read().splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            flush()
            buf = []
            heads = heads[: max(0, len(m.group(1)) - 2)] + [m.group(2).strip()]
        else:
            buf.append(line)
    flush()
json.dump(secs, open("wiki_sections.json", "w"), ensure_ascii=False)
print(len(secs), "sections")

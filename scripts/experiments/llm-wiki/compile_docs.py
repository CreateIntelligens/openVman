"""Compile the original non-QA catalog; keep experiment data outside the repo."""

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

from experiment_io import validate_output


DEFAULT_OUTPUT = Path(os.environ.get(
    "LLM_WIKI_OUTPUT_ROOT", Path.home() / "openvman-experiments/llm-wiki",
)).expanduser().resolve() / "heji"
CITE = re.compile(r"\[S\d+\]")
PROMPT = """將以下原始產品型錄區塊編譯為繁體中文主題 wiki。
只能使用提供的原文；保留型號、材質、適用條件、限制、選配、註腳、規格與數字。
不要由曲線、型號、相近機種或比例推算原文未列的數值，也不把最大揚程和最大流量當作同一工作點。
原文已配對的數值照原文描述，不要嘗試以工程常識修正。原文沒有就不要補。
每個條列只能有一句，每句末尾標來源 [S001]，可以多個；句號在來源前。
用 Markdown 標題和條列，不用表格；規格表按每個機型一條列，清楚寫出欄名、單位及數值。
不要遺漏有內容的區塊；標題可簡化但不要把不同產品混合。
輸出 JSON：{{"title":"主題標題","summary":"40字內、末尾附來源的一句摘要",
"keywords":["8至15個檢索關鍵詞"],"markdown":"完整markdown"}}
主題：{topic}
原文區塊：
{blocks}
"""


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def output_directory(value):
    path = validate_output(value)
    if path != DEFAULT_OUTPUT and DEFAULT_OUTPUT not in path.parents:
        raise ValueError(f"Output must be inside {DEFAULT_OUTPUT}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_source(container, source):
    # Reading through Docker respects the service's filesystem boundary.
    return subprocess.run(
        ["docker", "exec", container, "cat", source],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")


def source_blocks(text, max_chars=5000, *, source="catalog.md"):
    starts = {0, len(text)}
    starts.update(m.start() for m in re.finditer(r"(?m)^#{1,6} +", text))
    cuts = sorted(starts)
    spans = []
    for begin, end in zip(cuts, cuts[1:]):
        while end - begin > max_chars:
            cut = text.rfind("\n\n", begin + 1, begin + max_chars)
            if cut <= begin:
                cut = text.rfind("\n", begin + 1, begin + max_chars)
            cut = cut + 1 if cut > begin else begin + max_chars
            spans.append((begin, cut))
            begin = cut
        spans.append((begin, end))
    blocks = []
    parents = []
    for begin, end in spans:
        raw = text[begin:end]
        heading = re.match(r"(#{1,6}) +(.*)", raw)
        if heading:
            level = len(heading.group(1))
            parents = parents[:level - 1] + [heading.group(2).strip()]
        blocks.append({
            "id": f"S{len(blocks) + 1:03d}",
            "source": source,
            "heading": " > ".join(parents),
            "start_char": begin,
            "end_char": end,
            "text": raw,
        })
    assert "".join(b["text"] for b in blocks) == text
    return blocks


def page_groups(blocks):
    groups = []
    for block in blocks:
        match = re.match(r"## (第 (\d+) 頁：[^\n]+)", block["text"])
        if match:
            groups.append({
                "slug": f"catalog-{int(match.group(2)):02d}",
                "topic": match.group(1),
                "blocks": [],
            })
        if groups:
            groups[-1]["blocks"].append(block)
    if len(groups) != 20:
        raise ValueError(f"Expected 20 catalog pages; found {len(groups)}")
    return groups


def sections(pages):
    result = []
    for page in pages:
        heads, buf = [], []

        def flush():
            body = CITE.sub("", "\n".join(buf)).strip()
            if body:
                heading = " > ".join(heads)
                result.append({
                    "slug": page["slug"],
                    "title": page["title"],
                    "heading": heading,
                    "text": f"主題：{page['title']}\n{heading}\n{body}",
                })

        for line in page["markdown"].splitlines():
            match = re.match(r"^(#{1,6})\s+(.*)", line)
            if match:
                flush()
                buf = []
                heads = heads[:max(0, len(match.group(1)) - 2)] + [
                    CITE.sub("", match.group(2)).strip()
                ]
            else:
                buf.append(line)
        flush()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--source", default=os.environ.get("LLM_WIKI_CATALOG_SOURCE"),
        help="Absolute source path inside the container (or LLM_WIKI_CATALOG_SOURCE)",
    )
    parser.add_argument("--container", default="openvman-api-1")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    parts = PurePosixPath(args.source or "").parts
    if (len(parts) < 7 or parts[:3] != ("/", "data", "projects")
            or parts[4:6] != ("workspace", "knowledge")
            or ".." in parts or "\\" in (args.source or "")):
        parser.error("--source must name a file inside a container project's workspace/knowledge")
    outdir = output_directory(args.output)
    text = read_source(args.container, args.source)
    blocks = source_blocks(text, source=args.source)
    write_json(outdir / "src_blocks.json", blocks)
    groups = page_groups(blocks)
    wiki = outdir / "wiki"
    wiki.mkdir(exist_ok=True)
    os.environ.setdefault("LINT_MODEL", "gemini-3.8-flash")
    import llm

    def compile_page(group):
        prompt = PROMPT.format(
            topic=group["topic"],
            blocks="\n\n".join(
                f"[{b['id']}] {b['heading']}\n{b['text']}"
                for b in group["blocks"]
            ),
        )
        page = llm.gen(prompt, model="gemini-3.8-flash")
        for field in ("title", "summary", "markdown"):
            if not isinstance(page.get(field), str) or not page[field].strip():
                raise ValueError(f"Invalid {field}: {group['slug']}")
        if not isinstance(page.get("keywords"), list):
            raise ValueError(f"Invalid keywords: {group['slug']}")
        page["slug"] = group["slug"]
        page["source_rows"] = len(group["blocks"])
        return {k: page[k] for k in (
            "slug", "title", "summary", "keywords", "markdown", "source_rows"
        )}

    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        pages = list(pool.map(compile_page, groups))
    for page in pages:
        (wiki / f"{page['slug']}.md").write_text(page["markdown"] + "\n")
    write_json(wiki / "pages.json", pages)
    index = "# EVAK 產品型錄 Wiki\n\n" + "\n".join(
        f"- [{p['title']}]({p['slug']}.md)：{p['summary']}"
        for p in pages
    ) + "\n"
    (wiki / "index.md").write_text(index)
    section_list = sections(pages)
    write_json(outdir / "wiki_sections.json", section_list)
    report = {
        "model": "gemini-3.8-flash",
        "source": args.source,
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "source_characters": len(text),
        "source_blocks": len(blocks),
        "pages": len(pages),
        "sections": len(section_list),
        "uncompiled_blocks": [
            b["id"] for b in blocks
            if b["id"] not in {
                x["id"] for group in groups for x in group["blocks"]
            }
        ],
        "uncompiled_note": "文件前言及原始導航仍保存於來源；Wiki 導航另由各頁摘要建立。",
        "usage": llm.USAGE,
    }
    write_json(outdir / "compile_docs.json", report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

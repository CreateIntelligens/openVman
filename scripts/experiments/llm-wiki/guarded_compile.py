"""Build a traceable, extractive wiki snapshot from container-owned documents."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess

from experiment_io import validate_output
from grounded_claims import detect_instruction, validate_claim
from snapshot_store import open_snapshot, publish_snapshot


EXPORT_SCRIPT = r'''
import hashlib
import json
from pathlib import Path
import re
import sys

p = json.load(sys.stdin)
if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", p["project_id"]):
    raise ValueError("Invalid project")
root = (Path("/data/projects") / p["project_id"] / "workspace").resolve()
prefix = root / p["source_prefix"]
if not prefix.resolve().is_relative_to(root / "knowledge"):
    raise ValueError("Source must stay inside project knowledge")
paths = sorted(prefix.glob("*.csv")) if p["kind"] == "qa_csv" else [prefix]
if not paths:
    raise ValueError("No source files")
documents = []
for path in paths:
    if path.is_symlink() or not path.resolve().is_relative_to(root / "knowledge"):
        raise ValueError("Unsafe source path")
    raw = path.read_bytes()
    documents.append({"path": str(path.relative_to(root)),
                      "sha256": hashlib.sha256(raw).hexdigest(),
                      "text": raw.decode("utf-8-sig"), "persona_id": "default"})
print(json.dumps(documents, ensure_ascii=False))
'''


def encode_json(value):
    return json.dumps(value, ensure_ascii=False, indent=1) + "\n"


def source_units(documents, kind):
    """Parse complete rows/paragraphs without model-written factual content."""
    import csv
    import io

    units = []
    for document in documents:
        path = document["path"]
        if kind == "qa_csv":
            topic = re.sub(r"_IMG.*$|_qa_\d+$", "", Path(path).stem)
            for index, row in enumerate(csv.DictReader(io.StringIO(document["text"])), 1):
                question, answer = (row.get("q") or "").strip(), (row.get("a") or "").strip()
                if not question and not answer:
                    continue
                units.append({
                    "id": f"u{len(units) + 1:05d}", "path": path,
                    "topic": topic, "text": f"問題：{question}\n答覆：{answer}",
                    "question": question, "answer": answer,
                    "row_index": row.get("index") or str(index),
                })
        elif kind == "catalog_md":
            topic = Path(path).stem
            headings = []
            lines = document["text"].splitlines()
            buffer, kind_of_block = [], ""

            def flush():
                if buffer:
                    units.append({
                        "id": f"u{len(units) + 1:05d}", "path": path,
                        "topic": topic, "text": "\n".join(buffer),
                    })
                    buffer.clear()

            for line in lines:
                if re.match(r"^#{1,6}\s", line):
                    flush()
                    level = len(line) - len(line.lstrip("#"))
                    heading = re.sub(r"^#+\s*", "", line).strip()
                    headings = headings[:level - 1] + [heading]
                    topic = " > ".join(headings)
                    kind_of_block = ""
                elif not line.strip():
                    flush()
                    kind_of_block = ""
                else:
                    current_kind = "table" if line.lstrip().startswith("|") else "prose"
                    # A complete preceding statement can be retained when an
                    # explicit instruction starts on the next line. Incomplete
                    # clauses remain together and are quarantined conservatively.
                    if (
                        buffer and current_kind == kind_of_block == "prose"
                        and buffer[-1].rstrip().endswith(("。", "！", "？", ".", "!", "?"))
                        and detect_instruction(line)
                    ):
                        flush()
                    if kind_of_block and current_kind != kind_of_block:
                        flush()
                    buffer.append(line)
                    kind_of_block = current_kind
            flush()
        else:
            raise ValueError("Unknown source kind")
    return units


def build_snapshot(documents, *, project_id, kind, max_chars=1800):
    if not documents:
        raise ValueError("No documents; explicitly validate an empty replacement separately")
    if max_chars < 200:
        raise ValueError("Section budget is too small")
    manifest = {"project_id": project_id, "sources": {}}
    for document in documents:
        path = document["path"]
        if not path.startswith("knowledge/") or ".." in Path(path).parts:
            raise ValueError("Source path must be canonical project knowledge")
        if path in manifest["sources"]:
            raise ValueError("Duplicate source path")
        # Exporter hashes bytes before BOM removal. Keep that hash for runtime checks.
        manifest["sources"][path] = {
            "sha256": document["sha256"],
            "persona_id": document.get("persona_id", "default"), "refs": [],
        }
    units = source_units(documents, kind)
    sources = {unit["id"]: unit for unit in units}
    texts = {key: unit["text"] for key, unit in sources.items()}
    quarantine = []
    topics = defaultdict(list)
    for unit in units:
        violations = detect_instruction(unit["topic"]) + validate_claim(
            unit["text"], [unit["id"]], texts,
        )
        for field in ("question", "answer"):
            if field in unit:
                violations.extend(detect_instruction(unit[field]))
        if kind == "qa_csv" and not unit.get("answer"):
            violations.append("empty_answer")
        if violations:
            quarantine.append({"id": unit["id"], "path": unit["path"],
                               "violations": sorted(set(violations))})
            continue
        manifest["sources"][unit["path"]]["refs"].append(unit["id"])
        topics[unit["topic"]].append(unit)
    sections, pages = [], []
    for number, (topic, members) in enumerate(sorted(topics.items()), 1):
        slug = f"topic-{number:03d}"
        body = []
        group, chars = [], 0

        def flush():
            nonlocal chars
            if not group:
                return
            paths = sorted({unit["path"] for unit in group})
            personas = {manifest["sources"][path]["persona_id"] for path in paths}
            if len(personas) != 1:
                raise ValueError("Cannot compile across persona boundaries")
            sections.append({
                "id": f"section-{len(sections) + 1:04d}", "slug": slug,
                "title": topic, "heading": topic, "project_id": project_id,
                "persona_id": next(iter(personas)),
                "text": "主題：" + topic + "\n" + "\n\n".join(
                    unit["text"] + f" [{unit['id']}]" for unit in group
                ),
                "source_refs": [unit["id"] for unit in group],
                "source_paths": paths,
                "source_hashes": {path: manifest["sources"][path]["sha256"] for path in paths},
            })
            group.clear()
            chars = 0

        for unit in members:
            if group and chars + len(unit["text"]) > max_chars:
                flush()
            group.append(unit)
            chars += len(unit["text"])
            body.append(unit["text"] + f" [{unit['id']}]")
        flush()
        pages.append({"slug": slug, "title": topic, "summary": "原文條目分組",
                      "keywords": [], "source_rows": len(members),
                      "markdown": "# " + topic + "\n\n" + "\n\n".join(body)})
    if not sections:
        raise ValueError("All source units were rejected; no snapshot published")
    files = {
        "source_manifest.json": encode_json(manifest),
        "sources.json": encode_json(sources), "sections.json": encode_json(sections),
        "quarantine.json": encode_json(quarantine),
        "wiki/pages.json": encode_json([{k: v for k, v in p.items() if k != "markdown"} for p in pages]),
        "wiki/index.md": "# 原文分組目錄\n\n" + "\n".join(
            f"- [{p['title']}]({p['slug']}.md)" for p in pages
        ),
    }
    for page in pages:
        files[f"wiki/{page['slug']}.md"] = page["markdown"]
    files["compile_info.json"] = encode_json({
        "method": "extractive source-unit grouping; no generative factual prose",
        "project_id": project_id, "kind": kind, "source_count": len(documents),
        "source_units": len(units), "sections": len(sections), "pages": len(pages),
        "quarantined_units": len(quarantine), "max_chars": max_chars,
        "limitations": [
            "Instruction detector only covers known patterns, not all prompt injection.",
            "No semantic conflict resolver; contradictory source units remain distinct.",
            "Whole tables/QA rows are not truncated; some sections exceed budget.",
            "This changes the candidate; prior summarization accuracy does not transfer.",
        ],
    })
    return files, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--kind", choices=("qa_csv", "catalog_md"), required=True)
    parser.add_argument("--source-prefix", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-chars", type=int, default=1800)
    args = parser.parse_args()
    root = validate_output(args.output)
    result = subprocess.run(
        ["docker", "exec", "-i", "-w", "/app", "openvman-api-1", "python", "-c", EXPORT_SCRIPT],
        input=json.dumps({"project_id": args.project, "kind": args.kind,
                          "source_prefix": args.source_prefix}),
        text=True, capture_output=True,
    )
    if result.returncode:
        raise SystemExit(result.stderr[-2000:])
    documents = json.loads(result.stdout)
    files, manifest = build_snapshot(
        documents, project_id=args.project, kind=args.kind,
        max_chars=args.max_chars,
    )
    snapshot_id = publish_snapshot(root, files, manifest)
    snapshot = open_snapshot(root)
    info = json.loads((snapshot / "compile_info.json").read_text())
    print(json.dumps({"snapshot_id": snapshot_id, "root": str(root), **info}, ensure_ascii=False))


if __name__ == "__main__":
    main()

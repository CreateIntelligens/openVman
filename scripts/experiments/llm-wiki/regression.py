"""Recheck existing embedding questions through the read-only production tool."""

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import subprocess

from experiment_io import validate_output
import sweep_retrieval


HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = Path(os.environ.get(
    "LLM_WIKI_OUTPUT_ROOT", Path.home() / "openvman-experiments/llm-wiki",
)).expanduser().resolve() / "heji/embedding_regression"


def matched(rows, expected, limit):
    keys = expected.split("|")
    return any(any(key in row.get("text", "") for key in keys)
               for row in rows[:limit])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output = validate_output(args.output)
    args.output.mkdir(parents=True, exist_ok=True)
    questions, sources = [], {}
    for name in ("queries.json", "extra_queries.json"):
        path = HERE.parent / "embeddinggemma2" / name
        sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        for index, original in enumerate(json.loads(path.read_text())):
            if original["set"] not in ("kb", "xl", "asr", "noise"):
                continue
            if "expect" not in original:
                continue
            question = dict(original)
            question.setdefault("id", f"{path.stem}_{index:03d}")
            question.update(source_file=name, source_index=index,
                            original_id=original.get("id"))
            questions.append(question)
    if len({q["id"] for q in questions}) != len(questions):
        raise ValueError("Question IDs must be unique")
    (args.output / "questions.json").write_text(
        json.dumps(questions, ensure_ascii=False, indent=1)
    )
    payload = {
        "project_id": args.project, "questions": questions,
        "variants": sweep_retrieval.VARIANTS,
        "runtime": (HERE / "readonly_runtime.py").read_text(),
    }
    # Check both the cached singleton identity and its values after the context.
    bootstrap = (
        "from config import get_settings\n"
        "_baseline_cfg = get_settings()\n"
        "_baseline_values = _baseline_cfg.model_dump(mode='json')\n"
        + sweep_retrieval.CONTAINER_SCRIPT
        + "\nassert get_settings() is _baseline_cfg, 'Settings singleton changed'\n"
        "assert get_settings().model_dump(mode='json') == _baseline_values, 'Settings values changed'\n"
    )
    process = subprocess.run(
        ["docker", "exec", "-i", "-w", "/app", "openvman-api-1", "python", "-c", bootstrap],
        input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True,
    )
    (args.output / "stderr.txt").write_text(process.stderr)
    if process.returncode:
        raise SystemExit(process.stderr[-8000:])
    data = json.loads(next(line for line in reversed(process.stdout.splitlines())
                           if line.startswith("{")))
    if data["readonly_check"]["changed_paths"]:
        raise RuntimeError("Project data changed; discard run")
    data["config_unchanged"] = True
    (args.output / "retrieval.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1)
    )

    details, totals = [], defaultdict(lambda: defaultdict(int))
    for question in questions:
        noise = question["expect"] is None
        for variant, result in data["questions"][question["id"]].items():
            rows, related = result["results"], result["related"]
            item = {**question, "variant": variant, "noise": noise,
                    "result_count": len(rows), "related_count": len(related)}
            if not noise:
                item["hit_at_3"] = matched(rows, question["expect"], 3)
                item["hit_at_5"] = matched(rows, question["expect"], 5)
            details.append(item)
            groups = ("all", question["set"],
                      f"{question['set']}/{question['lang']}")
            for group in groups:
                values = totals[(variant, group)]
                if noise:
                    values["noise_questions"] += 1
                    values["noise_nonempty"] += bool(rows or related)
                    values["noise_primary_chunks"] += len(rows)
                    values["noise_related_chunks"] += len(related)
                else:
                    values["answerable_questions"] += 1
                    values["hit_at_3"] += item["hit_at_3"]
                    values["hit_at_5"] += item["hit_at_5"]
                    values["empty"] += not rows
    summary = {
        "project_id": args.project, "question_count": len(questions),
        "source_sha256": sources, "config_unchanged": True,
        "readonly_check": data["readonly_check"],
        "runtime_sha256": data["runtime_sha256"],
        "table_version": data["table_version"], "record_count": data["record_count"],
        "matching": "Case-sensitive literal expect alternatives in primary text; graph excluded from hit@k. Noise counts include primary and graph separately.",
        "timing": "Do not compare retrieval_ms: first variant includes query encoding; later variants share cached query vectors.",
        "id_generation": "Original files have no IDs; missing IDs use source stem plus original zero-based index. Original set/lang preserved.",
        "variants": {},
    }
    for variant in sweep_retrieval.VARIANTS:
        summary["variants"][variant] = {
            group: dict(values) for (name, group), values in totals.items()
            if name == variant
        }
    for name, value in (("details.json", details), ("summary.json", summary)):
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=1))
    for variant, groups in summary["variants"].items():
        print(variant, json.dumps(groups, ensure_ascii=False))
    print("readonly_check", json.dumps(data["readonly_check"]), "config_unchanged", True)


if __name__ == "__main__":
    main()

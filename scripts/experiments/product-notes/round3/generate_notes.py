"""Generate and validate notes in a disposable read-only API process."""

import argparse
from datetime import datetime, timezone
import json

from common import ROOT, mirror_check, run_container, write_json


def fresh_measurement():
    """Archive measured artifacts before a deliberate full rerun."""
    keep = {"questions.json", "question_validation.json", "table_rows.json",
            "previous_rounds_integrity.json", "previous_rounds.full.json"}
    paths = [path for path in ROOT.iterdir()
             if path.suffix in {".json", ".jsonl"} and path.name not in keep
             and not path.name.startswith("archived_measurement_")]
    if (ROOT / "notes").exists():
        paths.extend((ROOT / "notes").glob("*.md"))
    if not paths:
        return
    snapshot = {str(path.relative_to(ROOT)): path.read_text() for path in paths}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    write_json(f"archived_measurement_{stamp}.full.json", snapshot)
    for path in paths:
        path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh", action="store_true",
                        help="保存舊測量後重新生成；清除舊評分與檢查產物")
    args = parser.parse_args()
    if args.fresh:
        fresh_measurement()
    elif (ROOT / "generation.json").exists():
        raise RuntimeError("已有完成的生成；完整重跑請用 --fresh，驗證請用 verify_artifacts.py")
    mirror_check("mirror_before.json")
    prior = json.loads((ROOT.parent / "round2/generation.json").read_text())
    resume = {}
    journal = ROOT / "generation_checkpoint.jsonl"
    if journal.exists():
        events = [json.loads(line) for line in journal.read_text().splitlines()]
        candidates = [event["data"] for event in events
                      if event["type"] == "note_attempt"]
        resume = {
            "notes": [event["data"] for event in events
                      if event["type"] == "note"],
            "rejected_notes": [note for note in candidates
                               if note["validation"]["status"] == "failed"],
            "calls": [event["data"] for event in events
                      if event["type"] == "call"],
            "before": next(event["data"] for event in events
                           if event["type"] == "baseline"),
        }
    try:
        result = run_container({
            "operation": "generate",
            "source": (ROOT / "source_catalog.md").read_text(),
            "table_rows": json.loads((ROOT / "table_rows.json").read_text()),
            "model": prior["config"]["model"],
            "provider": prior["config"]["provider"],
            "temperature": prior["config"]["temperature"],
            "resume": resume,
        }, "generation_checkpoint.json")
        notes = ROOT / "notes"
        notes.mkdir(exist_ok=True)
        for note in result["notes"]:
            (notes / note["filename"]).write_text(note["markdown"] + "\n")
        write_json("generation.json", result)
    finally:
        mirror_check("mirror_after_generation.json")


if __name__ == "__main__":
    main()

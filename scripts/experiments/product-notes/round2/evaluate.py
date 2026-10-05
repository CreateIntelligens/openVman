"""Compare fixed-model A/B/C references for twelve frozen questions."""

import json

from common import ROOT, mirror_check, run_container, write_json


def main():
    generation = json.loads((ROOT / "generation.json").read_text())
    question_set = json.loads((ROOT / "questions.json").read_text())
    try:
        result = run_container({
            "operation": "evaluate",
            "source": (ROOT / "source_catalog.md").read_text(),
            "notes": generation["notes"],
            "model": generation["config"]["model"],
            "provider": generation["config"]["provider"],
            "questions": question_set["questions"],
        }, "evaluation_checkpoint.json")
        result["generation"] = generation
        result["question_set"] = question_set
        write_json("results.json", result)
    finally:
        mirror_check("mirror_after.json")


if __name__ == "__main__":
    main()

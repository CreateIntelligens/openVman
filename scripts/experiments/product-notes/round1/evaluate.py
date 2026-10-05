"""Compare A/B/C references; human source-grounded grading follows."""

import json

from common import ROOT, mirror_check, run_container, write_json


def main():
    generation = json.loads((ROOT / "generation.json").read_text())
    questions = json.loads((ROOT / "questions.json").read_text())
    try:
        result = run_container({
            "operation": "evaluate",
            "source": (ROOT / "source_catalog.md").read_text(),
            "notes": generation["notes"],
            "model": generation["config"]["model"],
            "provider": generation["config"]["provider"],
            "questions": questions["questions"],
        }, "evaluation_checkpoint.json")
        result["generation"] = generation
        result["question_set"] = questions
        write_json("results.json", result)
    finally:
        mirror_check("mirror_after.json")


if __name__ == "__main__":
    main()

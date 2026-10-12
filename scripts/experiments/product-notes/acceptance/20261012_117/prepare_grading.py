"""Export grading inputs without changing frozen questions or raw answers."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GROUPS = ((1, 7), (8, 14), (15, 20))


def main():
    questions = json.loads((ROOT / "questions.json").read_text())
    results = json.loads((ROOT / "results.json").read_text())
    assert results["status"] == "completed"
    for start, end in GROUPS:
        ids = {f"F{i:02}" for i in range(start, end + 1)}
        pack = {
            "grading_rubric": questions["grading_rubric"],
            "questions": [q for q in questions["questions"] if q["id"] in ids],
            "answers": [
                {key: row[key] for key in (
                    "id", "repeat", "question", "answer", "tool_steps",
                    "elapsed_seconds",
                )}
                for row in results["questions"] if row["id"] in ids
            ],
        }
        path = ROOT / f"answers_for_grading_F{start:02}_F{end:02}.json"
        if path.exists():
            assert json.loads(path.read_text()) == pack, (
                "Existing grading input differs; do not reuse prior grades"
            )
        else:
            path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n")
        print(path.name, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()

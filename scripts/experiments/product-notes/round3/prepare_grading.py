"""Export immutable completed answer batches while evaluation is running."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
GROUPS = ((1, 7), (8, 14), (15, 20))


def main():
    questions = json.loads((ROOT / "questions.json").read_text())
    rows = []
    checkpoint = ROOT / "evaluation_checkpoint.jsonl"
    if not checkpoint.exists():
        return
    for line in checkpoint.read_text().splitlines():
        # A running append can leave the final line incomplete.
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event["type"] == "question":
            rows.append(event["data"])
    for repeat in range(1, 4):
        for first, last in GROUPS:
            ids = {f"Q{index:02}" for index in range(first, last + 1)}
            selected = [row for row in rows
                        if row["repeat"] == repeat and row["id"] in ids]
            if len(selected) != len(ids):
                continue
            name = f"answers_for_grading_R{repeat}_Q{first:02}_Q{last:02}.json"
            path = ROOT / name
            data = {
                "grading_rubric": questions["grading_rubric"],
                "questions": [q for q in questions["questions"]
                              if q["id"] in ids],
                "answers": [{"id": row["id"], "repeat": repeat,
                             "answers": row["answers"]} for row in selected],
            }
            content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            if path.exists():
                assert path.read_text() == content, "完成的評分批次不可漂移"
            else:
                path.write_text(content)
                print(name)


if __name__ == "__main__":
    main()

"""Run four fixed-model arms three times on twenty frozen questions."""

import hashlib
import json

from common import ROOT, mirror_check, run_container, write_json


def main():
    if (ROOT / "results.json").exists() or (
            ROOT / "evaluation_checkpoint.jsonl").exists():
        raise RuntimeError("已有評測紀錄；不覆蓋或重複呼叫。完整重跑先 generate_notes.py --fresh")
    generation = json.loads((ROOT / "generation.json").read_text())
    frozen = json.loads((ROOT / "question_validation.json").read_text())
    assert hashlib.sha256((ROOT / "questions.json").read_bytes()).hexdigest() == (
        frozen["questions_sha256"])
    question_set = json.loads((ROOT / "questions.json").read_text())
    assert len(question_set["questions"]) == 20
    assert len(generation["notes"]) == 15
    assert all(n["validation"]["status"] == "passed"
               for n in generation["notes"])
    engine = (ROOT / "filter_engine.py").read_bytes()
    assert engine == (ROOT.parent / "round2/filter_engine.py").read_bytes()
    mirror_check("mirror_before_evaluation.json")
    try:
        result = run_container({
            "operation": "evaluate",
            "source": (ROOT / "source_catalog.md").read_text(),
            "notes": generation["notes"],
            "model": generation["config"]["model"],
            "provider": generation["config"]["provider"],
            "temperature": generation["config"]["temperature"],
            "filter_engine_sha256": hashlib.sha256(engine).hexdigest(),
            "filter_engine_source": engine.decode(),
            "questions": question_set["questions"],
        }, "evaluation_checkpoint.json")
        result["generation"] = generation
        result["question_set"] = question_set
        write_json("results.json", result)
    finally:
        mirror_check("mirror_after.json")


if __name__ == "__main__":
    main()

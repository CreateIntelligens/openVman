"""Verify frozen questions, original notes, filters, and read-only evidence."""

import hashlib
import json
from pathlib import Path

from filter_engine import evaluate_filters
from note_validation import parse_source_specs, validate_note


ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    if isinstance(value, list):
        return [canonical(item) for item in value]
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()
                if key != "source"}
    return value


def integrity(data):
    assert not data["changed"], data["changed"]
    assert data["digest_before"] == data["digest_after"]
    assert data["file_count_before"] == data["file_count_after"]


def main():
    source = (ROOT / "source_catalog.md").read_text()
    assert source == (ROOT.parent / "round2/source_catalog.md").read_text()
    assert (ROOT / "filter_engine.py").read_bytes() == (
        ROOT.parent / "round2/filter_engine.py").read_bytes()
    baseline = read("previous_rounds.full.json")
    assert all(digest(Path(path)) == value
               for path, value in baseline.items())
    questions = read("questions.json")
    old = json.loads((ROOT.parent / "round2/questions.json").read_text())
    assert questions["questions"][:12] == old["questions"]
    assert questions["grading_rubric"] == old["grading_rubric"]
    frozen = read("question_validation.json")
    assert digest(ROOT / "questions.json") == frozen["questions_sha256"]
    assert digest(ROOT / "table_rows.json") == frozen["table_rows_sha256"]
    assert digest(ROOT / "source_catalog.md") == frozen["source_sha256"]
    assert len(questions["questions"]) == 20
    assert [q["id"] for q in questions["questions"]] == [
        f"Q{index:02}" for index in range(1, 21)]
    lines = source.splitlines()
    citations = 0
    for question in questions["questions"]:
        for citation in question["sources"]:
            assert "\n".join(lines[citation["line_start"] - 1:
                                    citation["line_end"]]) == citation["quote"]
            citations += 1
    table_rows = read("table_rows.json")
    for row in table_rows:
        assert lines[row["line"] - 1] == row["row"]
    reference = parse_source_specs(table_rows)
    checks = {"status": "passed", "questions": 20,
              "citations": citations, "source_rows": 15,
              "old_questions_unchanged": True,
              "previous_rounds_unchanged": True,
              "filter_engine_unchanged": True}
    if (ROOT / "generation.json").exists():
        generated = read("generation.json")
        assert len(generated["notes"]) == 15
        by_model = {row["model"]: row for row in table_rows}
        audited = []
        for note in generated["notes"]:
            assert (ROOT / "notes" / note["filename"]).read_text().strip() == (
                note["markdown"].strip())
            result = validate_note(note["markdown"], note["frontmatter"],
                                   by_model[note["frontmatter"]["model"]], source)
            audited.append({"filename": note["filename"], **result})
            assert result["status"] == "passed", result
            label = (f"note-{note['frontmatter']['model']}"
                     f"-attempt{note['attempt']}")
            raw = next(c["content"] for c in generated["calls"]
                       if c["label"] == label)
            assert raw.strip().removeprefix("```markdown\n").removesuffix(
                "\n```").strip() == note["markdown"].strip()
        integrity(generated["integrity"])
        audit = {"notes": audited, "accepted_note_errors": 0,
                 "rejected_attempts": len(generated["rejected_notes"]),
                 "manual_edits": False}
        (ROOT / "note_audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
        checks["accepted_notes"] = 15
        checks["accepted_note_errors"] = 0
    if (ROOT / "results.json").exists():
        results = read("results.json")
        assert len(results["questions"]) == 60
        assert len(results["calls"]) == 300
        assert results["usage"]["missing_usage_calls"] == 0
        assert len({(q["id"], q["repeat"])
                    for q in results["questions"]}) == 60
        integrity(results["integrity"])
        assert generated["integrity"]["digest_after"] == (
            results["integrity"]["digest_before"])
        answer_calls = [c for c in results["calls"]
                        if not c["label"].startswith("filter-")]
        assert len(answer_calls) == 240
        assert len({c["system_sha256"] for c in answer_calls}) == 1
        assert {c["max_tokens"] for c in answer_calls} == {4200}
        assert all(c["model"] == results["config"]["model"]
                   for c in results["calls"] + generated["calls"])
        filters = []
        for row in results["questions"]:
            assert set(row["answers"]) == {"A", "B", "C", "D"}
            assert len(row["nearest_notes"]) == 3
            assert row["embedding_version"].split(":")[:5] == (
                row["note_embedding_identity"].split(":")[:5])
            assert row["embedding_version"].split(":")[-1] == (
                row["note_embedding_identity"].split(":")[-1])
            if row["filter_spec"] is not None:
                actual = evaluate_filters(row["filter_spec"], reference)
                assert canonical(actual) == canonical(row["frontmatter_filter"])
            else:
                filters.append({"id": row["id"], "repeat": row["repeat"],
                                **row["frontmatter_filter"]})
        checks["answer_count"] = 240
        checks["filter_errors"] = len(filters)
        (ROOT / "filter_audit.json").write_text(json.dumps(
            {"calls": 60, "schema_valid": 60 - len(filters), "errors": filters},
            ensure_ascii=False, indent=2) + "\n")
        for name in ("mirror_before.json", "mirror_after_generation.json",
                     "mirror_before_evaluation.json", "mirror_after.json"):
            assert read(name)["exit_code"] == 0
        if "summary" in results:
            for arm in "ABCD":
                assert sum(results["summary"]["all"][arm]["scores"].values()) == 60
    for path in ROOT.glob("*.py"):
        compile(path.read_text(), str(path), "exec")
    (ROOT / "verification.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(checks, ensure_ascii=False))


if __name__ == "__main__":
    main()

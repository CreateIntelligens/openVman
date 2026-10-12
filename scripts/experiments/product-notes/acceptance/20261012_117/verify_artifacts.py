"""Fail on source, freeze, answer, grading or read-only evidence drift.

This checks measurement integrity; a passed check does not mean the model
answered correctly. It never calls a provider or opens the live database.
"""

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics

from freeze_questions import main as verify_freeze
from prepare_grading import GROUPS, main as verify_packs

ROOT = Path(__file__).resolve().parent
VERDICTS = {
    "correct": "對", "partial": "部分對", "wrong": "錯",
    "對": "對", "部分對": "部分對", "錯": "錯",
}


def load(name):
    return json.loads((ROOT / name).read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def count_grades(rows):
    counts = Counter(row["verdict"] for row in rows)
    return {key: counts[key] for key in ("對", "部分對", "錯")}


def main():
    verify_freeze()
    verify_packs()
    raw = load("results.json")
    freeze = load("question_validation.json")
    assert raw["status"] == "completed" and raw["error"] is None
    assert raw["questions_sha256"] == digest(ROOT / "questions.json")
    assert raw["questions_sha256"] == freeze["questions_sha256"]
    assert raw["questions_frozen_at"] == freeze["frozen_at_utc"]
    assert datetime.fromisoformat(raw["checkout"]["snapshot_at"]) > (
        datetime.fromisoformat(freeze["frozen_at_utc"])
    )
    manifest = raw["checkout"]["source_manifest"]
    manifest_hash = text_digest(json.dumps(
        manifest, sort_keys=True, separators=(",", ":"),
    ))
    assert manifest_hash == raw["bundle_sha256"]
    questions = load("questions.json")["questions"]
    oracle = {q["id"]: q for q in questions}
    expected = {(q["id"], repeat) for q in questions for repeat in (1, 2, 3)}
    answers = {(r["id"], r["repeat"]): r for r in raw["questions"]}
    assert len(raw["questions"]) == len(answers) == 60
    assert set(answers) == expected
    assert len({r["final"]["session_id"] for r in answers.values()}) == 60
    for (qid, repeat), row in answers.items():
        assert row["question"] == oracle[qid]["question"]
        assert row["answer"].strip()
        assert row["final"]["reply"] == row["answer"]
        assert row["final"]["status"] == "ok"
        assert row["final"]["request_context"]["metadata"] == {}
        assert row["final"]["session_id"] == f"accept117-R{repeat}-{qid}"
        assert row["final"]["history"][0]["content"] == row["question"]
        assert len(row["final"]["history"]) == 2
    assert raw["calls"] == [call for row in raw["questions"] for call in row["calls"]]
    assert all(call["status"] == "ok" and call["usage"] for call in raw["calls"])
    assert len(raw["decision_calls"]) == 60
    assert all(r["decision"]["status"] == "available" for r in answers.values())
    assert load("full_process.json")["exit_code"] == 0
    parity = load("behavior_parity.json")
    assert raw["behavior_parity"] == parity
    assert parity["raw_metadata_equal"] is False
    assert parity["resolved_metadata_equal"] is True
    parity_check = load("parity_verification.json")
    assert parity_check["status"] == "verified"
    assert parity_check["raw_metadata_sha256"] == parity["raw_metadata_sha256"]
    assert parity_check["different_language_cache_entries"] == 99
    assert parity_check["document_entries"] == 129
    assert parity_check["knowledge_contents_equal"] is True
    for mode in ("full", "probe2"):
        result = raw if mode == "full" else load("probe2_results.json")
        integrity = result["integrity"]
        assert integrity["changed"] == []
        assert integrity["sha256_before"] == integrity["sha256_after"]
        assert integrity["file_count_before"] == integrity["file_count_after"] == 967
        full_path = ROOT / f"{mode}_integrity.full.json"
        if full_path.exists():
            full = json.loads(full_path.read_text())
            assert full["before"] == full["after"]
            assert len(full["before"]) == 967
        for suffix in ("before", "after"):
            mirror = load(f"mirror_{mode}_{suffix}.json")
            assert mirror["exit_code"] == 1
            assert mirror["stderr"].splitlines()[1] == "  內容不同：.doc_meta.json"
    grades = {}
    grading_hashes = {}
    for start, end in GROUPS:
        suffix = f"F{start:02}_F{end:02}.json"
        pack_path = ROOT / ("answers_for_grading_" + suffix)
        grade_path = ROOT / ("grading_" + suffix)
        pack = json.loads(pack_path.read_text())
        document = json.loads(grade_path.read_text())
        assert document["input_sha256"] == digest(pack_path)
        grading_hashes[grade_path.name] = digest(grade_path)
        keys = {(r["id"], r["repeat"]) for r in pack["answers"]}
        seen = set()
        for row in document["grades"]:
            key = (row["id"], row["repeat"])
            assert key in keys and key not in seen and key not in grades
            seen.add(key)
            assert row["answer_sha256"] == text_digest(answers[key]["answer"])
            verdict = VERDICTS[row["verdict"]]
            assert row["reason"] and row["source_lines"]
            if verdict == "對":
                assert not row["missing_points"] and not row["false_claims"]
            if verdict == "部分對":
                assert row["missing_points"] and not row["false_claims"]
            if verdict == "錯":
                assert row["false_claims"]
            grades[key] = {**row, "verdict": verdict}
        assert seen == keys
    assert set(grades) == expected
    audit = load("tool_audit.json")
    assert audit["results_sha256"] == digest(ROOT / "results.json")
    assert audit["status"] == "verified"
    assert len(audit["code_matches_recorded_manifest"]) == 3
    assert all(value is True for value in audit["code_matches_recorded_manifest"].values())
    assert audit["frozen_source_file_hashes_verified"] == 120
    assert len(audit["questions"]) == 60
    assert {(r["id"], r["repeat"]) for r in audit["questions"]} == expected
    assert audit["summary"]["filter_call_count"] == sum(
        t["name"] == "filter_products" for r in answers.values() for t in r["tool_steps"]
    )
    assert audit["summary"]["computation_mismatch_calls"] == 0
    assert audit["summary"]["independent_partition_mismatches"] == 0
    elapsed = sorted(row["elapsed_seconds"] for row in answers.values())
    usage = {
        key: sum(c["usage"].get(key, 0) for c in raw["calls"])
        for key in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens")
    }
    per_question = []
    for q in questions:
        rows = [grades[q["id"], repeat] for repeat in (1, 2, 3)]
        per_question.append({
            "id": q["id"], "kind": q["kind"],
            "verdicts": [r["verdict"] for r in rows],
            "counts": count_grades(rows),
            "grades": rows,
        })
    summary = {
        "status": "verified", "answer_count": 60, "fresh_session_count": 60,
        "source_notes": 117, "source_series": 18, "source_citations": 181,
        "results_sha256": digest(ROOT / "results.json"),
        "questions_sha256": raw["questions_sha256"],
        "grading_sha256": grading_hashes,
        "tool_audit_sha256": digest(ROOT / "tool_audit.json"),
        "scores": count_grades(grades.values()),
        "per_repeat": {
            str(repeat): count_grades([r for (qid, rep), r in grades.items() if rep == repeat])
            for repeat in (1, 2, 3)
        },
        "all_three_correct": [q["id"] for q in per_question if q["counts"]["對"] == 3],
        "per_question": per_question,
        "answer_stage_llm_calls": len(raw["calls"]),
        "answer_stage_provider_attempts": len(raw["route_attempts"]),
        "decision_provider_calls": len(raw["decision_calls"]),
        "probe_answer_count_excluded_from_scoring": len(load("probe2_results.json")["questions"]),
        "probe_llm_calls_separate": len(load("probe2_results.json")["calls"]),
        "probe_decision_calls_separate": len(load("probe2_results.json")["decision_calls"]),
        "answer_stage_usage": usage,
        "tools": dict(Counter(t["name"] for r in answers.values() for t in r["tool_steps"])),
        "tool_audit": audit["summary"],
        "timing_seconds": {
            "p50": statistics.median(elapsed), "p90_nearest_rank": elapsed[53],
            "sum": sum(elapsed), "includes": "Brain generation only; excludes HTTP/Backend/TTS",
        },
        "integrity": raw["integrity"], "behavior_parity": parity,
        "limitations": raw["limitations"],
    }
    (ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in (
        "status", "answer_count", "scores", "per_repeat", "all_three_correct",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()

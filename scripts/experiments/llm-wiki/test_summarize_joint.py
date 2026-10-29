"""Reported dynamic and replay gains must remain tied to actual evidence."""

from copy import deepcopy
import hashlib
import json
import unittest

from summarize_joint import apply_overrides, validate_batch, validate_replay


def fixture():
    cases = [{"id": "A", "q": "Question"}]
    live = {
        "config_unchanged": True, "readonly_check": {"changed_paths": []},
        "retrieval_mode": "dynamic", "records": [], "errors": [],
        **{field: "same" for field in ("project_id", "persona_id", "production_code_sha256",
            "dynamic_source_sha256", "inputs_sha256", "answer_policy", "history_policy", "context_policy")},
    }
    grades = []
    for rep in range(2):
        row = {"id": "A", "rep": rep, "variant": "focused_v2", "q": "Question", "history": [],
               "prompt_messages": [{"role": "system", "content": "System"},
                                   {"role": "user", "content": "Question"}],
               "answer": "Answer", "error": None, "source_access_gate": True, "unauthorized_sources": [],
               "tool_steps": [{"result": json.dumps({"status": "ok", "data": {
                   "results": [{"text": "Evidence"}], "related": [], "queries": []}})}],
               "retrieval_trace": [{"profile": "focused_v2", "selected_chars": 8}]}
        live["records"].append(row)
        grades.append({"id": "A", "rep": rep, "variant": "focused_v2", "answer": "Answer",
                       "context": "Evidence", "system_context": "System",
                       "system_sha256": hashlib.sha256(b"System").hexdigest(),
                       "pass": True, "critical": False})
    return cases, live, grades


class JointSummaryTests(unittest.TestCase):
    def test_complete_dynamic_evidence_passes(self):
        self.assertEqual(len(validate_batch(*fixture())[0]), 2)

    def test_missing_repetition_and_changed_context_cannot_look_successful(self):
        cases, live, grades = fixture()
        live["records"].pop()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            validate_batch(cases, live, grades)
        cases, live, grades = fixture()
        grades[0]["context"] = "Better evidence that was never supplied"
        with self.assertRaisesRegex(ValueError, "differs"):
            validate_batch(cases, live, grades)

    def test_dynamic_trace_and_source_access_are_required(self):
        for change in ({"retrieval_trace": []}, {"unauthorized_sources": ["disabled"]}):
            cases, live, grades = fixture()
            live["records"][0].update(change)
            with self.assertRaises(ValueError):
                validate_batch(cases, live, grades)

    def test_checker_replay_must_keep_actual_original_context(self):
        _, original, _ = fixture()
        checked = deepcopy(original)
        checked["check_readonly"] = {"changed_paths": []}
        for row in checked["records"]:
            row.update(precheck_answer="Answer", answer="Checked answer",
                       answer_check={"original_answer": "Answer", "final_answer": "Checked answer"})
        validate_replay(original, checked)
        checked["records"][0]["retrieval_trace"] = [{"other": "new source"}]
        with self.assertRaisesRegex(ValueError, "Replay changed"):
            validate_replay(original, checked)

    def test_published_repair_requires_its_own_intact_verification(self):
        _, original, _ = fixture()
        checked = deepcopy(original)
        checked["check_readonly"] = {"changed_paths": []}
        for row in checked["records"]:
            row.update(precheck_answer="Answer", answer="Corrected.", answer_check={
                "original_answer": "Answer", "checked_answer": "Corrected.", "final_answer": "Corrected.",
                "repair": {"draft": "Corrected.", "verification": {
                    "original_answer": "Corrected.", "final_answer": "Corrected.", "action": "accept",
                    "spans": [{"text": "Corrected.", "status": "nonfactual"}]}}})
        validate_replay(original, checked)
        checked["records"][0]["answer_check"]["repair"]["verification"]["action"] = "unsupported"
        with self.assertRaisesRegex(ValueError, "independently verified"):
            validate_replay(original, checked)

    def test_prompt_budget_failure_still_remains_in_the_denominator(self):
        cases, live, grades = fixture()
        error = {"type": "ValueError", "message": "history budget exceeded"}
        row = live["records"][0]
        row.update(prompt_messages=[], tool_steps=[], retrieval_trace=[], answer="", error=error)
        live["errors"] = [{"id": row["id"], "error": error}]
        grades[0].update(answer="", context="（沒有找到資料）", system_context="",
                         system_sha256=hashlib.sha256(b"").hexdigest(),
                         execution_error=error, **{"pass": False})
        self.assertEqual(len(validate_batch(cases, live, grades)[0]), 2)

    def test_review_cannot_waive_disabled_source_access(self):
        key = ("A", 0, "focused_v2")
        batches = {"batch": {key: {"pass": False, "critical": True, "unauthorized_sources": ["disabled"]}}}
        review = {"input_sha256": {}, "overrides": [{"batch": "batch", "id": "A", "rep": 0,
            "variant": "focused_v2", "old_pass": False, "old_critical": True,
            "new_pass": True, "new_critical": False, "reason": "Attempt to waive source boundary"}]}
        with self.assertRaisesRegex(ValueError, "source-access"):
            apply_overrides(batches, review, set())


if __name__ == "__main__":
    unittest.main()

"""Citation schema recovery may never recover an invented source or agent failure."""

from copy import deepcopy
import json
import unittest

from reprocess_checks import reprocess_row


def fixture():
    reply = {"action": "accept", "reason": "literal", "spans": [{
        "text": "Rated current 22 A.", "status": "supported", "evidence": ["E0:L0"], "operational": []}]}
    return {"answer": "Rejected", "prompt_messages": [{"role": "system", "content": "這一輪的回答語言：English。"}],
            "error": {"type": "AnswerCheckFailed", "message": "evidence_check_failed"},
            "tool_steps": [{"result": json.dumps({"data": {"results": [{"text": "Rated current 22 A."}], "related": []}})}],
            "answer_check": {"error": "evidence_check_failed", "original_answer": "Rated current 22 A.",
                "final_answer": "Rejected", "scope": {"needs_clarification": False}, "scope_attempts": [],
                "attempts": [{"response_content": json.dumps(reply)}]}}


class ReprocessTests(unittest.TestCase):
    def test_real_line_reference_recovers_without_generating_any_new_text(self):
        original = fixture()
        before = deepcopy(original)
        row = reprocess_row(original)
        self.assertEqual(row["answer"], "Rated current 22 A.")
        self.assertIsNone(row["error"])
        self.assertEqual(row["previous_check_error"], original["error"])
        self.assertEqual(original, before)
        self.assertEqual(row["tool_steps"], original["tool_steps"])

    def test_unknown_line_does_not_recover(self):
        original = fixture()
        original["answer_check"]["attempts"][0]["response_content"] = original["answer_check"]["attempts"][0]["response_content"].replace("E0:L0", "E9:L999")
        self.assertEqual(reprocess_row(original), original)

    def test_unrelated_agent_failure_is_never_cleared(self):
        original = fixture()
        original["error"] = {"type": "PermissionError", "message": "Blocked mutation"}
        self.assertEqual(reprocess_row(original)["error"], original["error"])

    def test_failed_scope_is_never_reinterpreted_as_success(self):
        original = fixture()
        original["answer_check"]["error"] = "scope_check_failed"
        self.assertEqual(reprocess_row(original), original)

    def test_saved_repair_proof_is_never_replaced_by_its_initial_rejection(self):
        original = fixture()
        original["answer_check"]["repair"] = {"draft": "Verified repair", "verification": {"action": "accept"}}
        self.assertEqual(reprocess_row(original), original)

    def test_failed_repair_can_only_recover_when_saved_initial_proof_now_accepts(self):
        original = fixture()
        original["answer_check"].update(error="repair_generation_failed", repair={"error": "RuntimeError"})
        result = reprocess_row(original)
        self.assertIsNone(result["error"])
        self.assertEqual(result["answer"], "Rated current 22 A.")
        self.assertIn("repair", result["previous_check"])
        raw = original["answer_check"]["attempts"][0]
        raw["response_content"] = raw["response_content"].replace('"accept"', '"unsupported"')
        self.assertEqual(reprocess_row(original), original)


if __name__ == "__main__":
    unittest.main()

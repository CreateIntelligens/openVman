"""Check comparison isolation and fail closed when the budget is insufficient."""

import unittest

from answer_policy import apply_policy, policy_metadata


class AnswerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.messages = [
            {"role": "system", "content": "existing project rules"},
            {"role": "user", "content": "prior subject"},
            {"role": "assistant", "content": "prior answer"},
            {"role": "user", "content": "follow-up"},
        ]

    def test_production_is_an_independent_exact_copy(self):
        result = apply_policy(self.messages, "production", total_char_budget=1)
        self.assertEqual(result, self.messages)
        result[0]["content"] = "changed"
        self.assertEqual(self.messages[0]["content"], "existing project rules")

    def test_candidate_preserves_history_question_and_original_rules(self):
        result = apply_policy(self.messages, "evidence_v1", total_char_budget=10000)
        self.assertEqual(result[1:], self.messages[1:])
        self.assertTrue(result[0]["content"].startswith(self.messages[0]["content"] + "\n\n"))
        self.assertEqual(self.messages[0]["content"], "existing project rules")

    def test_budget_overflow_fails_instead_of_losing_subject(self):
        with self.assertRaisesRegex(ValueError, "history preserved"):
            apply_policy(self.messages, "evidence_v1", total_char_budget=10)
        self.assertEqual(len(self.messages), 4)

    def test_unknown_policy_and_non_system_prefix_fail(self):
        with self.assertRaises(ValueError):
            apply_policy(self.messages, "unreviewed", total_char_budget=10000)
        with self.assertRaises(ValueError):
            apply_policy(self.messages[1:], "evidence_v1", total_char_budget=10000)

    def test_metadata_is_stable_and_makes_prompt_only_scope_explicit(self):
        meta = policy_metadata("evidence_v1")
        self.assertEqual(meta, policy_metadata("evidence_v1"))
        self.assertEqual(len(meta["sha256"]), 64)
        self.assertGreater(meta["added_chars"], 0)
        self.assertIn("no deterministic", meta["scope"])


if __name__ == "__main__":
    unittest.main()

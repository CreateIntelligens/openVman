"""Check stability summaries reject corrupted or incomplete evidence."""

import copy
import itertools
import unittest

from stability import summarize


class StabilitySummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = []
        labels = ("chat", "knowledge", "web", "clarify")
        for repeat in range(3):
            for order, options in enumerate(itertools.permutations(labels)):
                for case in range(32):
                    self.rows.append({
                        "id": f"case-{case}", "repeat": repeat,
                        "order_index": order, "execution_index": len(self.rows),
                        "prompt_sha256": f"{case}-{order}",
                        "option_ids": options, "predicted": "knowledge",
                        "expected": "knowledge", "probabilities": [.25] * 4,
                        "option_logits": [1.] * 4, "total_seconds": .01,
                        "winner_position": options.index("knowledge"),
                        "top_tied": True,
                    })
        self.metadata = {
            "planned_predictions": len(self.rows),
            "schedule": [[row["repeat"], row["order_index"], row["id"]]
                         for row in self.rows],
        }

    def test_stable_outputs(self) -> None:
        result = summarize(self.rows, self.metadata)
        self.assertEqual(result["identical_input_groups"], 768)
        self.assertEqual(result["first_repeat_order_sensitive_cases"], 0)
        self.assertEqual(result["first_repeat_always_correct_cases"], 32)
        self.assertEqual(result["repeat_flip_groups"], [])
        self.assertEqual(result["max_repeat_probability_delta"], 0)

    def test_repeat_flip_and_order_sensitivity_are_separate(self) -> None:
        self.rows[768]["predicted"] = "chat"
        self.rows[768]["probabilities"] = [.4, .2, .2, .2]
        result = summarize(self.rows, self.metadata)
        self.assertEqual(len(result["repeat_flip_groups"]), 1)
        self.assertEqual(result["first_repeat_order_sensitive_cases"], 0)
        self.assertAlmostEqual(result["max_repeat_probability_delta"], .15)

    def test_first_repeat_order_change(self) -> None:
        self.rows[0]["predicted"] = "chat"
        result = summarize(self.rows, self.metadata)
        self.assertEqual(result["first_repeat_order_sensitive_cases"], 1)
        self.assertEqual(result["first_repeat_always_correct_cases"], 31)

    def test_incomplete_run_rejected(self) -> None:
        with self.assertRaises(AssertionError):
            summarize(self.rows[:-1], self.metadata)

    def test_duplicate_repeat_rejected_even_with_modified_schedule(self) -> None:
        self.rows[768] = copy.deepcopy(self.rows[0])
        self.rows[768]["execution_index"] = 768
        self.metadata["schedule"][768] = self.metadata["schedule"][0]
        with self.assertRaises(AssertionError):
            summarize(self.rows, self.metadata)

    def test_wrong_execution_order_rejected(self) -> None:
        self.rows[0], self.rows[1] = self.rows[1], self.rows[0]
        with self.assertRaises(AssertionError):
            summarize(self.rows, self.metadata)

    def test_changed_prompt_rejected(self) -> None:
        self.rows[768]["prompt_sha256"] = "different input"
        with self.assertRaises(AssertionError):
            summarize(self.rows, self.metadata)


if __name__ == "__main__":
    unittest.main()

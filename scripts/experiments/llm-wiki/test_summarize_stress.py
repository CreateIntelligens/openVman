"""Check that report bookkeeping cannot hide dropped or altered evidence."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from summarize_stress import metrics, reviewed_rows, unique_keys


class SummaryTests(unittest.TestCase):
    def test_duplicate_answers_are_rejected(self):
        row = {"id": "c", "rep": 0, "variant": "baseline"}
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            unique_keys([row, row])

    def test_execution_failure_remains_in_denominator(self):
        rows = [
            {"variant": "b", "pass": False, "critical": False,
             "execution_error": "empty"},
            {"variant": "b", "pass": True, "critical": False},
        ]
        result = metrics(rows)["b"]
        self.assertEqual((result["count"], result["passed"], result["execution_errors"]),
                         (2, 1, 1))

    def test_review_bound_to_exact_raw_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.json"
            path.write_text("[]")
            review = {"raw_results_sha256": hashlib.sha256(b"[]").hexdigest(),
                      "overrides": []}
            path.write_text("[ ]")
            with self.assertRaisesRegex(ValueError, "does not match"):
                reviewed_rows([], review, path)

    def test_override_cannot_rewrite_different_old_label(self):
        rows = [{"id": "c", "rep": 0, "variant": "b", "pass": False, "critical": True}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.json"
            path.write_text(json.dumps(rows))
            review = {"raw_results_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "overrides": [{**rows[0], "old_pass": True,
                                     "old_critical": True, "new_pass": True,
                                     "new_critical": False}]}
            with self.assertRaisesRegex(ValueError, "old values differ"):
                reviewed_rows(rows, review, path)


if __name__ == "__main__":
    unittest.main()

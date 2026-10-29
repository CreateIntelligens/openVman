"""Offline contract checks for the synthetic stress harness."""

from collections import Counter
import os
from pathlib import Path
import tempfile
import unittest

import compile_stress as stress


class CompileStressTests(unittest.TestCase):
    def test_case_matrix(self):
        cases = stress.build_cases()
        self.assertEqual(len(cases), 24)
        self.assertEqual(len({case["id"] for case in cases}), 24)
        self.assertEqual(Counter(c["phase"] for c in cases), {
            "compile": 12, "answer": 8, "lifecycle": 2,
            "offline": 1, "lint": 1,
        })
        self.assertTrue(all(c["criteria"] for c in cases))

    def test_exact_existing_prompt_extraction(self):
        prompt = stress.prompt_constant("compile.py", "PROMPT")
        self.assertIn("知識庫說法不一", prompt)
        self.assertIn("原文沒有就不要補", stress.prompt_constant("compile_docs.py", "PROMPT"))
        self.assertIn("ids 只能用", stress.prompt_constant("lint.py", "PROMPT"))

    def test_fixture_revision_is_explicit_and_bounded(self):
        original = {c["id"]: c for c in stress.build_cases(1)}
        revised = {c["id"]: c for c in stress.build_cases(2)}
        self.assertEqual([key for key in original if original[key] != revised[key]], ["C01", "A06"])
        self.assertIn("下午不開放", revised["A06"]["source"])

    def test_citation_audit_does_not_skip_uncited_or_bad_refs(self):
        checks = stress.citation_checks("# Test\nNo reference\n- Bad [S999]", {"S001"})
        by_name = {c["name"]: c["pass"] for c in checks}
        self.assertFalse(by_name["all_content_lines_cited"])
        self.assertFalse(by_name["no_unknown_citations"])
        self.assertFalse(stress.citation_checks("", {"S001"})[0]["pass"])

    def test_real_compile_rerun_records_deletion_regression(self):
        stress.OUTPUT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=stress.OUTPUT) as directory:
            previous = Path.cwd()
            try:
                result = stress.lifecycle_worker("L01", Path(directory))
            finally:
                os.chdir(previous)
            checks = {c["name"]: c["pass"] for c in result["checks"]}
            self.assertTrue(checks["modified_fact_replaced"])
            # This test checks that the harness observes the existing bug.
            self.assertFalse(checks["deleted_pages_removed"])


if __name__ == "__main__":
    unittest.main()

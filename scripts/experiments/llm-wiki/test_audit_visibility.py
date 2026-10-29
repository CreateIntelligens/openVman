"""Check the acceptance gate with actual reference envelope shapes."""

import unittest

from audit_visibility import audit


class VisibilityTests(unittest.TestCase):
    def test_disabled_related_reference_also_fails(self):
        data = {"questions": {"c": {"candidate": {
            "results": [{"path": "public"}], "related": [{"path": "disabled"}],
        }}}}
        report = audit(data, ["disabled"])
        self.assertFalse(report["passed"])
        self.assertEqual(report["variants"]["candidate"]["affected_cases"], 1)

    def test_allowed_references_pass(self):
        data = {"questions": {"c": {"baseline": {
            "results": [{"path": "public"}], "related": [],
        }}}}
        self.assertTrue(audit(data, ["disabled"])["passed"])

    def test_name_substrings_do_not_imply_disable(self):
        data = {"questions": {"c": {"baseline": {
            "results": [{"path": "public-copy"}], "related": [],
        }}}}
        self.assertTrue(audit(data, ["public"])["passed"])


if __name__ == "__main__":
    unittest.main()

"""A paired check must operate on the real draft, never a previous canned rejection."""

from contextvars import ContextVar
import unittest

from recheck_answers import parallel_checks, restore_draft


class RestoreDraftTests(unittest.TestCase):
    def test_restore_keeps_previous_failure_and_exact_original_draft(self):
        row = {"answer": "Canned rejection", "error": {"type": "AnswerCheckFailed", "message": "failed"},
               "answer_check": {"original_answer": "Actual original draft", "final_answer": "Canned rejection"}}
        restore_draft(row)
        self.assertEqual(row["answer"], "Actual original draft")
        self.assertIsNone(row["error"])
        self.assertEqual(row["source_check_error"]["type"], "AnswerCheckFailed")
        self.assertEqual(row["source_answer_check"]["final_answer"], "Canned rejection")

    def test_restoration_never_clears_an_agent_or_permission_failure(self):
        row = {"answer": "old", "error": {"type": "PermissionError", "message": "Blocked mutation"},
               "answer_check": {"original_answer": "original"}}
        restore_draft(row)
        self.assertEqual(row["error"]["type"], "PermissionError")
        self.assertNotIn("source_check_error", row)

    def test_parallel_checks_copy_project_context_without_leaking_worker_changes(self):
        project = ContextVar("test_project", default="unscoped")
        token = project.set("bound-project")
        try:
            def run(row):
                current = project.get()
                project.set("worker-only")
                return (row, current)
            results = dict(parallel_checks(range(6), run, 2))
            self.assertEqual(results, {i: (i, "bound-project") for i in range(6)})
            self.assertEqual(project.get(), "bound-project")
        finally:
            project.reset(token)


if __name__ == "__main__":
    unittest.main()

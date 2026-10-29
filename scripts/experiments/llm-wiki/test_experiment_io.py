"""Check privacy and source-preservation boundaries without model calls."""

from pathlib import Path
import tempfile
import unittest

from experiment_io import validate_output


class OutputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()

    def test_repository_and_worktree_outputs_are_rejected(self):
        for path in (self.repo / "data.json", self.repo / ".worktree/x/data.json"):
            with self.assertRaisesRegex(ValueError, "outside repositories"):
                validate_output(path, roots=[self.repo])

    def test_symlink_into_repository_is_rejected(self):
        link = self.root / "alias"
        link.symlink_to(self.repo, target_is_directory=True)
        with self.assertRaises(ValueError):
            validate_output(link / "data.json", roots=[self.repo])

    def test_same_input_or_hardlink_is_rejected(self):
        source = self.root / "questions.json"
        source.write_text("[]")
        alias = self.root / "alias.json"
        alias.hardlink_to(source)
        for path in (source, alias):
            with self.assertRaisesRegex(ValueError, "overwrite"):
                validate_output(path, inputs=[source], roots=[self.repo])
        self.assertEqual(source.read_text(), "[]")

    def test_external_output_is_allowed(self):
        target = self.root / "out/results.json"
        self.assertEqual(validate_output(target, roots=[self.repo]), target)


if __name__ == "__main__":
    unittest.main()

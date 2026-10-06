"""Check rerun archiving preserves frozen evidence and blocks stale answers."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import evaluate
import generate_notes


ROOT = Path(__file__).resolve().parent


class RunnerGuards(unittest.TestCase):
    def test_fresh_archives_before_removing_only_measured_artifacts(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            frozen = ("questions.json", "question_validation.json",
                      "table_rows.json", "previous_rounds_integrity.json",
                      "previous_rounds.full.json", "source_catalog.md")
            for name in frozen:
                (root / name).write_text("frozen evidence")
            (root / "results.json").write_text("old answers")
            (root / "grading_R1_Q01_Q07.json").write_text("old grades")
            (root / "evaluation_checkpoint.jsonl").write_text("old calls")
            (root / "notes").mkdir()
            (root / "notes/model.md").write_text("original note")

            def archive(name, data):
                (root / name).write_text(json.dumps(data))

            with patch.object(generate_notes, "ROOT", root), patch.object(
                    generate_notes, "write_json", archive):
                generate_notes.fresh_measurement()
            saved = list(root.glob("archived_measurement_*.full.json"))
            self.assertEqual(len(saved), 1)
            data = json.loads(saved[0].read_text())
            self.assertEqual(data["results.json"], "old answers")
            self.assertEqual(data["notes/model.md"], "original note")
            self.assertEqual(len(data), 4)
            self.assertTrue(all((root / name).read_text() == "frozen evidence"
                                for name in frozen))
            self.assertFalse((root / "results.json").exists())
            self.assertFalse((root / "notes/model.md").exists())

    def test_evaluation_refuses_existing_results_or_incomplete_checkpoint(self):
        for name in ("results.json", "evaluation_checkpoint.jsonl"):
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                    dir=ROOT) as directory:
                root = Path(directory)
                (root / name).write_text("must remain unchanged")
                with patch.object(evaluate, "ROOT", root), patch.object(
                        evaluate, "run_container") as run:
                    with self.assertRaisesRegex(RuntimeError, "已有評測紀錄"):
                        evaluate.main()
                    run.assert_not_called()
                self.assertEqual((root / name).read_text(), "must remain unchanged")


if __name__ == "__main__":
    unittest.main()

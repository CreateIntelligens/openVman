"""Protect the distinction between source issues, fixtures and unverified lint."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import offline_review as review


class OfflineReviewTests(unittest.TestCase):
    def test_only_actual_source_changes_are_synthetic(self):
        original = [{"file":"fixture.csv", "index":"1", "q":"Question", "a":"10"}]
        finding = {"type":"contradiction", "ids":["fixture.csv#1"], "summary":"Preserve"}
        same = review.review_packet(original, original, [finding])["findings"][0]
        changed = review.review_packet(original, [{**original[0], "a":"20"}], [finding])["findings"][0]
        self.assertEqual(same["disposition"], "review_required")
        self.assertEqual(changed["disposition"], "synthetic_fixture")
        self.assertFalse(changed["approved"])
        self.assertEqual(changed["finding"], finding)
        self.assertEqual(changed["original_sources"]["fixture.csv#1"]["a"], "10")

    def test_unknown_refs_are_preserved_and_duplicate_sources_rejected(self):
        finding = {"ids":["missing#1"], "type":"incomplete"}
        packet = review.review_packet([], [], [finding])
        self.assertEqual(packet["findings"][0]["disposition"], "unresolved_reference")
        self.assertEqual(packet["findings"][0]["unknown_refs"], ["missing#1"])
        row = {"file":"a", "index":"1", "q":"q", "a":"a"}
        with self.assertRaises(ValueError):
            review.row_map([row, row])

    def test_cli_keeps_hashes_and_does_not_echo_private_text_or_trust_plants(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = {"file":"fixture.csv", "index":"1", "q":"PRIVATE_QUESTION", "a":"PRIVATE_ANSWER"}
            values = {"original.json":[row], "lint.json":[row],
                      "findings.json":[{"ids":["fixture.csv#1"]}],
                      "plants.json":[{"row":"fixture.csv#1"}]}
            for name, value in values.items():
                (root/name).write_text(json.dumps(value))
            output = root/"review.json"
            argv = [review.__file__, "--original-rows", str(root/"original.json"),
                    "--lint-rows", str(root/"lint.json"), "--findings", str(root/"findings.json"),
                    "--plants", str(root/"plants.json"), "--output", str(output)]
            stdout = io.StringIO()
            with patch("sys.argv", argv), contextlib.redirect_stdout(stdout):
                review.main()
            data = json.loads(output.read_text())
            self.assertEqual(data["findings"][0]["disposition"], "review_required")
            self.assertNotIn("PRIVATE", stdout.getvalue())
            self.assertEqual(len(data["input_sha256"]), 4)
            for filename, digest in data["input_sha256"].items():
                self.assertEqual(hashlib.sha256(Path(filename).read_bytes()).hexdigest(), digest)
            with patch("sys.argv", argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    review.main()
            with patch("sys.argv", [*argv[:-1], str(root/"original.json")]):
                with self.assertRaises(ValueError):
                    review.main()
            with patch("sys.argv", [*argv[:-1], str(Path(review.__file__).parent/"private-review.json")]):
                with self.assertRaises(ValueError):
                    review.main()


if __name__ == "__main__":
    unittest.main()

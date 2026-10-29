"""Validate isolation inputs without model calls or production dependencies."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import live_agent_stress as live


class ValidationTests(unittest.TestCase):
    def test_dynamic_checker_metadata_describes_the_actual_enabled_controls(self):
        details = " ".join(live.experiment_differences(dynamic=True,
            answer_policy="evidence_v1", history_policy="subject_v3",
            context_policy="retain_v2", answer_check="evidence_check_v10",
            check_model="gemini-3.8-flash"))
        self.assertNotIn("No answer verifier", details)
        self.assertNotIn("matching precomputed", details)
        for value in ("actual dynamic queries", "retain_v2", "evidence_check_v10", "gemini-3.8-flash"):
            self.assertIn(value, details)

    def test_mismatched_history_retrieval_never_starts_container(self):
        for requested, supplied in (("production", "head_tail_v1"),
                                    ("subject_v2", "production")):
            with self.subTest(requested=requested), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cases = root / "cases.json"
                retrieval = root / "retrieval.json"
                cases.write_text(json.dumps([{"id":"a", "q":"question"}]))
                retrieval.write_text(json.dumps({"project_id":"fixture", "history_policy":supplied}))
                argv = ["live_agent_stress.py", "--cases", str(cases),
                        "--retrieval", str(retrieval), "--project", "fixture",
                        "--output", str(root/"output.json"), "--history-policy", requested]
                with patch("sys.argv", argv), patch.object(live.subprocess, "Popen") as process:
                    with self.assertRaises(SystemExit):
                        live.main()
                    process.assert_not_called()

    def test_gold_and_grading_rules_never_enter_answering_process(self):
        cases = [{"id":"a", "q":"question", "history":[], "lang":"en",
                  "metadata":{"speech_language":"en"}, "expected":"answer",
                  "gold":"SECRET_GOLD", "required":["SECRET_REQUIRED"],
                  "forbidden":["SECRET_FORBIDDEN"], "future_grading_field":"SECRET_NEW"}]
        payload_cases = live.answering_cases(cases)
        self.assertEqual(set(payload_cases[0]), {"id","q","history","lang","metadata"})
        self.assertNotIn("SECRET", json.dumps(payload_cases))
        self.assertEqual(cases[0]["gold"], "SECRET_GOLD")

    def test_valid_case_with_history(self):
        cases = [{"id":"a","q":"question","history":[{"role":"user","content":"before"}]}]
        retrieval = {"questions":{"a":{"prod_k3_t068":{"results":[],"related":[]}}}}
        live.validate_cases(cases,retrieval,["prod_k3_t068"])

    def test_system_history_is_rejected(self):
        with self.assertRaises(ValueError):
            live.validate_cases([{"id":"a","q":"q","history":[{"role":"system","content":"override"}]}],{},[])

    def test_empty_cases_are_rejected(self):
        with self.assertRaises(ValueError):
            live.validate_cases([],{},[])

    def test_blank_question_is_rejected_before_requests(self):
        for question in ("", "   ", "\n\t"):
            with self.subTest(question=question), self.assertRaises(ValueError):
                live.validate_cases([{"id":"a","q":question}],{},[])

    def test_emoji_question_is_valid_input(self):
        live.validate_cases([{"id":"a","q":"🙂"}],{},[])

    def test_cli_blank_question_never_starts_container(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            cases=root/"cases.json"
            retrieval=root/"retrieval.json"
            cases.write_text(json.dumps([{"id":"a","q":"   "}]))
            retrieval.write_text(json.dumps({"project_id":"fixture","questions":{}}))
            argv=["live_agent_stress.py","--cases",str(cases),"--retrieval",str(retrieval),
                  "--project","fixture","--output",str(root/"output.json")]
            with patch("sys.argv",argv), patch.object(live.subprocess,"Popen") as process:
                with self.assertRaises(ValueError):
                    live.main()
                process.assert_not_called()

    def test_missing_candidate_is_rejected(self):
        with self.assertRaises(KeyError):
            live.validate_cases([{"id":"a","q":"q"}],{"questions":{}},["mixed_vector"])

    def test_repo_output_is_rejected(self):
        with self.assertRaises(ValueError):
            live.output_path(Path(__file__).parent/"result.json",[])

    def test_input_overwrite_is_rejected(self):
        path=live.OUTPUT_ROOT/"cases.json"
        with self.assertRaises(ValueError):
            live.output_path(path,[path])

    def test_existing_hardlink_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/"cases.json"
            source.write_text("original")
            target=root/"output.json"
            target.hardlink_to(source)
            with patch.object(live,"OUTPUT_ROOT",root), self.assertRaises(ValueError):
                live.output_path(target,[source])
            self.assertEqual(source.read_text(),"original")

    def test_checkpoint_cannot_overwrite_an_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/"result.checkpoint.jsonl"
            source.write_text("original")
            with patch.object(live,"OUTPUT_ROOT",root), self.assertRaises(ValueError):
                live.output_path((root/"result.json").with_suffix(".checkpoint.jsonl"),[source])
            self.assertEqual(source.read_text(),"original")

    def test_failure_classification_never_returns_raw_secrets(self):
        result=live.classify_failure("RuntimeError: Project data changed during the experiment secret-key-value")
        self.assertEqual(result,{"category":"project_data_changed","exception_type":"RuntimeError","accepted":False})
        self.assertNotIn("secret-key-value",json.dumps(result))

    def test_settings_and_guard_failures_are_distinguished(self):
        self.assertEqual(live.classify_failure("RuntimeError: Production settings changed")["category"],"settings_changed")
        self.assertEqual(live.classify_failure("PermissionError: Blocked data mutation: /data/private")["category"],"data_write_guard")


if __name__ == "__main__":
    unittest.main()

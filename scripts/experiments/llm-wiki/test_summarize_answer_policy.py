"""Synthetic evidence integrity tests; no production questions or private data."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from answer_policy import EVIDENCE_V1, policy_metadata
import summarize_answer_policy as summary


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def create_batch(root, count=32):
    for domain in summary.DOMAINS:
        directory = root / domain
        cases = [{"id": f"case{i}", "q": f"Fixture question {i}",
                  "history": [{"role": "user", "content": "Previous fixture question"}],
                  "gold": "JUDGE ONLY"} for i in range(count)]
        cases_path, retrieval_path = directory / "cases.json", directory / "retrieval.json"
        result = {"text": "Fixture source", "path": "knowledge/fixture.txt"}
        data = {"results": [result], "related": [], "queries": ["fixture"]}
        write(cases_path, cases)
        write(retrieval_path, {"project_id": "fixture-project", "questions": {
            c["id"]: {"safe_mixed": data} for c in cases}})
        for profile, policy in summary.PROFILES.items():
            records, grades = [], []
            for rep in range(2):
                for case in cases:
                    system = "Fixture system\n- current_time: 2026-10-28 10:00:00 CST (Wednesday)"
                    if profile == "candidate":
                        system += "\n\n" + EVIDENCE_V1
                    record = {"id": case["id"], "rep": rep, "variant": "safe_mixed",
                              "q": case["q"], "history": case["history"],
                              "answer": "Fixture answer", "answer_policy": policy_metadata(policy),
                              "prompt_messages": [{"role": "system", "content": system},
                                                  *case["history"],
                                                  {"role": "user", "content": case["q"]}],
                              "tool_steps": [{"call_id": f"{profile}-{rep}",
                                              "result": json.dumps({"status": "ok", "data": data})}],
                              "models": ["fixture-model"], "error": None}
                    grade = {"id": case["id"], "rep": rep, "variant": "safe_mixed",
                             "answer": record["answer"], "context": result["text"],
                             "system_context": system, "system_sha256": hashlib.sha256(system.encode()).hexdigest(),
                             "pass": True, "critical": False}
                    records.append(record)
                    grades.append(grade)
            live = {"records": records, "errors": [], "project_id": "fixture-project",
                    "persona_id": "default", "answer_policy": policy_metadata(policy),
                    "config_unchanged": True, "readonly_check": {"file_count": 1, "changed_paths": []},
                    "inputs_sha256": {str(p): summary.digest(p) for p in (cases_path, retrieval_path)},
                    "production_code_sha256": {"agent": "fixture-code-hash"},
                    "workspace_documents": {"identity": {"sha256": "fixture-doc-hash"}},
                    "configured_chain": [{"provider": "fixture", "model": "fixture-model"}],
                    "answer_policy_source_sha256": "fixture-policy-code-hash",
                    "runner_sha256": "fixture-runner-hash", "runtime_sha256": "fixture-runtime-hash",
                    "disabled_paths": []}
            write(directory / f"{profile}_live.json", live)
            write(directory / f"{profile}_judged.json", grades)


class AnswerPolicySummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "answer_policy_v1"
        create_batch(self.root)

    def edit(self, filename, change, domain="hospital"):
        path = self.root / domain / filename
        value = json.loads(path.read_text())
        change(value)
        write(path, value)

    def review(self, domain="hospital", overrides=None):
        directory = self.root / domain
        value = {"input_sha256": {f"{p}_judged.json": summary.digest(directory / f"{p}_judged.json")
                                  for p in summary.PROFILES},
                 "overrides": overrides or [], "review_scope": "Synthetic complete review"}
        write(directory / "review.json", value)
        return value

    def override(self, **updates):
        return {"profile": "candidate", "id": "case0", "rep": 0, "variant": "safe_mixed",
                "old_pass": True, "new_pass": False, "old_critical": False,
                "new_critical": True, "reason": "Synthetic adjudication", **updates}

    def reject(self, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            summary.summarize(self.root)

    def test_complete_unreviewed_batch_has_exact_denominators(self):
        result = summary.summarize(self.root)
        self.assertEqual(result["status"], "NOT_READY")
        hospital = result["batches"]["main"]["hospital"]
        self.assertEqual(hospital["raw"]["candidate"]["count"], 64)
        self.assertEqual(hospital["paired_raw"]["both_pass"], 64)
        self.assertEqual(hospital["review_status"], "unreviewed")
        self.assertNotIn("reviewed", hospital)
        self.assertEqual(len(hospital["evidence_sha256"]), 6)

    def test_complete_review_and_holdout_never_certifies_production(self):
        holdout = Path(self.temp.name) / "holdout"
        create_batch(holdout, 12)
        for domain in summary.DOMAINS:
            self.review(domain)
            directory = holdout / domain
            write(directory / "review.json", {"input_sha256": {
                f"{p}_judged.json": summary.digest(directory / f"{p}_judged.json")
                for p in summary.PROFILES}, "overrides": []})
        result = summary.summarize(self.root, holdout)
        self.assertEqual(result["status"], "NOT_CERTIFIED")
        self.assertEqual(result["batches"]["holdout"]["heji"]["reviewed"]["control"]["count"], 24)

    def test_missing_judgments_rejected(self):
        (self.root / "hospital/candidate_judged.json").unlink()
        self.reject("Missing or invalid")

    def test_duplicate_live_answer_rejected(self):
        self.edit("candidate_live.json", lambda v: v["records"].append(deepcopy(v["records"][0])))
        self.reject("Duplicate")

    def test_duplicate_judgment_rejected(self):
        self.edit("candidate_judged.json", lambda v: v.append(deepcopy(v[0])))
        self.reject("Duplicate")

    def test_wrong_case_with_same_answer_count_rejected(self):
        self.edit("candidate_live.json", lambda v: v["records"][0].update(id="unknown"))
        self.reject("distribution")

    def test_wrong_repetition_with_same_answer_count_rejected(self):
        self.edit("candidate_live.json", lambda v: v["records"][0].update(rep=2))
        self.reject("distribution")

    def test_missing_one_repetition_rejected(self):
        self.edit("candidate_live.json", lambda v: v["records"].pop())
        self.edit("candidate_judged.json", lambda v: v.pop())
        self.reject("distribution")

    def test_answer_tampering_rejected(self):
        self.edit("candidate_judged.json", lambda v: v[0].update(answer="Altered answer"))
        self.reject("Judged answer")

    def test_grade_context_tampering_rejected(self):
        self.edit("candidate_judged.json", lambda v: v[0].update(context="Altered context"))
        self.reject("context/system")

    def test_grade_system_tampering_rejected(self):
        self.edit("candidate_judged.json", lambda v: v[0].update(system_context="Altered system"))
        self.reject("context/system")

    def test_grade_system_hash_tampering_rejected(self):
        self.edit("candidate_judged.json", lambda v: v[0].update(system_sha256="wrong"))
        self.reject("system hash")

    def test_case_source_hash_tampering_rejected(self):
        path = self.root / "hospital/cases.json"
        path.write_text(path.read_text() + " ")
        self.reject("Input hash mismatch")

    def test_retrieval_source_hash_tampering_rejected(self):
        path = self.root / "hospital/retrieval.json"
        path.write_text(path.read_text() + " ")
        self.reject("Input hash mismatch")

    def test_code_difference_rejected(self):
        self.edit("candidate_live.json", lambda v: v["production_code_sha256"].update(agent="changed"))
        self.reject("production_code_sha256")

    def test_workspace_difference_rejected(self):
        self.edit("candidate_live.json", lambda v: v["workspace_documents"].update(extra="changed"))
        self.reject("workspace_documents")

    def test_provider_chain_difference_rejected(self):
        self.edit("candidate_live.json", lambda v: v["configured_chain"][0].update(model="different-model"))
        self.reject("configured_chain")

    def test_failed_readonly_check_rejected(self):
        self.edit("candidate_live.json", lambda v: v["readonly_check"].update(changed_paths=["fixture"]))
        self.reject("Read-only")

    def test_actual_queries_differ_despite_equal_retrieval_hash_rejected(self):
        def change(value):
            step = value["records"][0]["tool_steps"][0]
            result = json.loads(step["result"])
            result["data"]["queries"] = ["different"]
            step["result"] = json.dumps(result)
        self.edit("candidate_live.json", change)
        self.reject("actual tool context")

    def test_actual_source_path_differs_despite_equal_text_rejected(self):
        def change(value):
            step = value["records"][0]["tool_steps"][0]
            result = json.loads(step["result"])
            result["data"]["results"][0]["path"] = "knowledge/other.txt"
            step["result"] = json.dumps(result)
        self.edit("candidate_live.json", change)
        self.reject("actual tool context")

    def test_actual_related_text_difference_with_matching_grade_rejected(self):
        def change(value):
            step = value["records"][0]["tool_steps"][0]
            result = json.loads(step["result"])
            result["data"]["related"] = [{"text": "Other fixture", "path": "knowledge/other.txt"}]
            step["result"] = json.dumps(result)
        self.edit("candidate_live.json", change)
        self.edit("candidate_judged.json", lambda v: v[0].update(context="Fixture source\n\nOther fixture"))
        self.reject("actual tool context")

    def test_candidate_history_prompt_change_rejected(self):
        self.edit("candidate_live.json", lambda v: v["records"][0]["prompt_messages"][1].update(content="Changed history"))
        self.reject("fixed evidence policy")

    def change_clock(self, old, new):
        def live(value):
            for row in value["records"]:
                row["prompt_messages"][0]["content"] = row["prompt_messages"][0]["content"].replace(old, new)
        def grades(value):
            for row in value:
                row["system_context"] = row["system_context"].replace(old, new)
                row["system_sha256"] = hashlib.sha256(row["system_context"].encode()).hexdigest()
        self.edit("candidate_live.json", live)
        self.edit("candidate_judged.json", grades)

    def test_only_execution_clock_seconds_may_differ(self):
        self.change_clock("10:00:00", "11:12:13")
        result = summary.summarize(self.root)["batches"]["main"]["hospital"]
        self.assertIn("11:12:13", result["execution_clocks"]["candidate"][0])
        self.assertNotIn("prompt_messages", result)

    def test_compressed_inline_execution_clock_is_supported(self):
        def flatten_live(value):
            for row in value["records"]:
                messages = row["prompt_messages"]
                messages[0]["content"] = messages[0]["content"].replace(
                    "Fixture system\n- current_time:", "Fixture system - current_time:",
                )
        def flatten_grade(value):
            for row in value:
                row["system_context"] = row["system_context"].replace(
                    "Fixture system\n- current_time:", "Fixture system - current_time:",
                )
                row["system_sha256"] = hashlib.sha256(row["system_context"].encode()).hexdigest()
        for profile in summary.PROFILES:
            self.edit(f"{profile}_live.json", flatten_live)
            self.edit(f"{profile}_judged.json", flatten_grade)
        self.change_clock("10:00:00", "11:12:13")
        data = summary.summarize(self.root)["batches"]["main"]["hospital"]
        self.assertIn("11:12:13", data["execution_clocks"]["candidate"][0])

    def test_clock_date_change_rejected(self):
        self.change_clock("2026-10-28", "2026-10-29")
        self.reject("fixed evidence policy")

    def test_clock_timezone_change_rejected(self):
        self.change_clock("CST", "UTC")
        self.reject("fixed evidence policy")

    def test_critical_pass_rejected(self):
        self.edit("candidate_judged.json", lambda v: v[0].update(critical=True))
        self.reject("cannot pass")

    def test_review_is_separate_and_paired_regression_visible(self):
        raw_path = self.root / "hospital/candidate_judged.json"
        before = raw_path.read_bytes()
        self.review(overrides=[self.override()])
        data = summary.summarize(self.root)["batches"]["main"]["hospital"]
        self.assertEqual(data["raw"]["candidate"]["passed"], 64)
        self.assertEqual(data["reviewed"]["candidate"]["passed"], 63)
        self.assertEqual(data["paired_reviewed"]["pass_to_fail"], 1)
        self.assertEqual(raw_path.read_bytes(), before)

    def test_stale_review_hash_rejected(self):
        self.review()
        path = self.root / "hospital/candidate_judged.json"
        path.write_text(path.read_text() + " ")
        self.reject("Review input hash")

    def test_review_old_label_mismatch_rejected(self):
        self.review(overrides=[self.override(old_pass=False)])
        self.reject("old values differ")

    def test_review_must_bind_both_profiles(self):
        self.review()
        self.edit("review.json", lambda v: v["input_sha256"].pop("control_judged.json"))
        self.reject("both raw judgments")

    def test_duplicate_review_override_rejected(self):
        self.review(overrides=[self.override(), self.override()])
        self.reject("Duplicate review")

    def test_review_cannot_make_critical_answer_pass(self):
        self.review(overrides=[self.override(new_pass=True)])
        self.reject("cannot pass")

    def test_judge_error_is_counted_and_cannot_pass(self):
        self.edit("candidate_judged.json", lambda v: v[0].update({"pass": False, "judge_error": "FixtureFailure"}))
        data = summary.summarize(self.root)["batches"]["main"]["hospital"]
        self.assertEqual(data["raw"]["candidate"]["judge_errors"], 1)
        self.assertEqual(data["paired_raw"]["pass_to_fail"], 1)

    def test_paired_improvement_is_not_hidden(self):
        self.edit("control_judged.json", lambda v: v[0].update({"pass": False, "critical": True}))
        data = summary.summarize(self.root)["batches"]["main"]["hospital"]
        self.assertEqual(data["paired_raw"]["fail_to_pass"], 1)
        self.assertEqual(data["raw"]["control"]["critical"], 1)

    def test_codepoint_length_observation_does_not_relabel_content(self):
        answer = "長" * 80 + "🙂"
        self.edit("candidate_live.json", lambda v: v["records"][0].update(answer=answer))
        self.edit("candidate_judged.json", lambda v: v[0].update(answer=answer))
        data = summary.summarize(self.root)["batches"]["main"]["hospital"]
        self.assertEqual(data["reply_length_codepoints"]["candidate"]["max"], 81)
        self.assertEqual(data["reply_length_codepoints"]["candidate"]["over_80_codepoints"], 1)
        self.assertEqual(data["raw"]["candidate"]["passed"], 64)

    def test_execution_failure_stays_in_denominator(self):
        def fail(value):
            value["records"][0].update(error={"type": "FixtureError"}, answer="")
            value["errors"] = [{"id": "case0", "variant": "safe_mixed", "type": "FixtureError"}]
        self.edit("candidate_live.json", fail)
        self.edit("candidate_judged.json", lambda v: v[0].update({"answer": "", "pass": False, "execution_error": "FixtureError"}))
        data = summary.summarize(self.root)["batches"]["main"]["hospital"]
        self.assertEqual(data["raw"]["candidate"]["count"], 64)
        self.assertEqual(data["raw"]["candidate"]["execution_errors"], 1)

    def run_cli(self, output):
        return subprocess.run([sys.executable, str(Path(summary.__file__)),
                               "--root", str(self.root), "--output", str(output)],
                              capture_output=True, text=True)

    def test_cli_writes_external_summary_and_rejects_overwrite(self):
        output = Path(self.temp.name) / "summary.json"
        self.assertEqual(self.run_cli(output).returncode, 0)
        before = output.read_bytes()
        self.assertNotEqual(self.run_cli(output).returncode, 0)
        self.assertEqual(output.read_bytes(), before)

    def test_cli_rejects_input_overwrite(self):
        path = self.root / "hospital/candidate_judged.json"
        before = path.read_bytes()
        result = self.run_cli(path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("overwrite", result.stderr)
        self.assertEqual(path.read_bytes(), before)

    def test_cli_rejects_repository_output_before_creation(self):
        path = Path(summary.__file__).parent / "must-not-create-summary.json"
        result = self.run_cli(path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside repositories", result.stderr)
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()

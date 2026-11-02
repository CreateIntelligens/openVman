"""Synthetic pairing, immutable-grade and strict acceptance boundary tests."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compare_followup import compare_records, main


def fixture(questions=4, arms=("main", "candidate")):
    live, judged = [], []
    for variant in arms:
        for cid in range(questions):
            for rep in range(3):
                key = {"id": "question-" + str(cid), "rep": rep, "variant": variant}
                live.append({**key, "answer": "synthetic answer", "error": None,
                             "latency": {"first_text_ms": 1000}})
                judged.append({**key, "answer": "synthetic answer",
                               "pass": False, "critical": False})
    return {"records": live, "arms": {arm: {} for arm in arms}}, judged


def set_pass(judged, variant, ids, reps=range(3)):
    for row in judged:
        if (row["variant"] == variant and row["id"] in ids
                and row["rep"] in reps):
            row["pass"] = True


class CompareFollowupTests(unittest.TestCase):
    def test_gain_two_is_small_but_three_passes_gain_gate(self):
        for count in (2, 3):
            with self.subTest(count=count):
                live, judged = fixture()
                set_pass(judged, "candidate", {"question-" + str(i) for i in range(count)})
                result = compare_records(live, judged)
                arm = result["arms"]["candidate"]
                self.assertEqual(arm["delta_vs_main"]["per_round_questions"], [count] * 3)
                self.assertEqual(arm["delta_vs_main"]["total_passes"], count * 3)
                self.assertEqual(arm["delta_vs_main"]["average_questions_per_round"], count)
                self.assertEqual(arm["delta_vs_main"]["operational_small"], count == 2)
                self.assertEqual(arm["gates"]["gain"], count == 3)
                self.assertEqual(arm["all_core_gates_pass"], count == 3)
                self.assertTrue(result["statistical_interpretation"]["not_a_p_value"])
                self.assertFalse(result["statistical_interpretation"]["statistical_significance_claimed"])

    def test_three_rounds_and_full_96_denominator_include_failures(self):
        live, judged = fixture(32)
        live["records"][-1]["error"] = "provider failure"
        live["records"][-1]["answer"] = ""
        judged[-1]["answer"] = ""
        original = copy.deepcopy((live, judged))
        result = compare_records(live, judged)
        arm = result["arms"]["candidate"]
        self.assertEqual(result["pairs_per_arm"], 96)
        self.assertEqual(arm["denominator"], 96)
        self.assertEqual(arm["failed"], 96)
        self.assertEqual([r["denominator"] for r in arm["per_round"]], [32] * 3)
        self.assertEqual(arm["errors"], 1)
        self.assertEqual(arm["error_counts"]["execution"], 1)
        self.assertEqual(arm["paired_first_text_latency"]["measured_pairs"], 95)
        self.assertFalse(arm["gates"]["latency"])
        self.assertEqual((live, judged), original)

    def test_single_pass_regression_and_stable_baseline_are_both_reported(self):
        live, judged = fixture()
        set_pass(judged, "main", {"question-0"}, [0])
        set_pass(judged, "main", {"question-1"})
        set_pass(judged, "candidate", {"question-1"}, [0, 1])
        arm = compare_records(live, judged)["arms"]["candidate"]
        self.assertEqual(arm["main_pass_candidate_fail_pairs"], [
            {"id": "question-0", "rep": 0}, {"id": "question-1", "rep": 2},
        ])
        self.assertEqual(arm["main_three_of_three_pass_candidate_fail_questions"], [])
        self.assertTrue(arm["gates"]["no_regression"])
        # Two failures cross the agreed threshold; a single noisy miss does not.
        next(r for r in judged if r["variant"] == "candidate"
             and r["id"] == "question-1" and r["rep"] == 1)["pass"] = False
        arm = compare_records(live, judged)["arms"]["candidate"]
        self.assertEqual(arm["main_three_of_three_pass_candidate_fail_questions"], [
            {"id": "question-1", "failing_reps": [1, 2]},
        ])
        self.assertFalse(arm["gates"]["no_regression"])

    def test_max_latency_boundary_and_nearest_rank_p90(self):
        live, judged = fixture(1)
        rows = [r for r in live["records"] if r["variant"] == "candidate"]
        for row, value in zip(rows, [900, 1100, 1200]):
            row["latency"]["first_text_ms"] = value
        arm = compare_records(live, judged)["arms"]["candidate"]
        latency = arm["paired_first_text_latency"]
        self.assertEqual(latency["median_added_ms"], 100)
        self.assertEqual(latency["p90_added_ms"], 200)
        self.assertEqual(latency["max_added_ms"], 200)
        self.assertTrue(arm["gates"]["latency"])
        rows[-1]["latency"]["first_text_ms"] = 1200.001
        arm = compare_records(live, judged)["arms"]["candidate"]
        self.assertFalse(arm["gates"]["latency"])
        self.assertEqual(arm["paired_first_text_latency"]["over_limit_pairs"][0]["rep"], 2)

    def test_missing_invalid_and_execution_failure_timings_never_pass(self):
        for value in (None, True, "1000", float("nan"), float("inf"), -1):
            with self.subTest(value=value):
                live, judged = fixture(1)
                live["records"][-1]["latency"]["first_text_ms"] = value
                arm = compare_records(live, judged)["arms"]["candidate"]
                self.assertFalse(arm["gates"]["latency"])
                self.assertEqual(len(arm["paired_first_text_latency"]["missing_pairs"]), 1)
        live, judged = fixture(1)
        for row in live["records"]:
            row["error"] = "failed"
            row["latency"]["first_text_ms"] = 0
        arm = compare_records(live, judged)["arms"]["candidate"]
        self.assertEqual(arm["paired_first_text_latency"]["measured_pairs"], 0)
        self.assertIsNone(arm["paired_first_text_latency"]["median_added_ms"])
        self.assertEqual(arm["errors"], 3)
        self.assertEqual(arm["failed"], 3)

    def test_missing_baseline_timing_fails_even_when_all_grades_pass(self):
        live, judged = fixture(1)
        for row in judged:
            row["pass"] = True
        live["records"][0].pop("latency")
        arm = compare_records(live["records"], judged)["arms"]["candidate"]
        self.assertEqual(arm["pass"], 3)
        self.assertEqual(arm["denominator"], 3)
        self.assertFalse(arm["gates"]["latency"])
        self.assertEqual(arm["paired_first_text_latency"]["missing_pairs"], [{
            "id": "question-0", "rep": 0,
            "main_first_text_ms": None, "candidate_first_text_ms": 1000,
        }])

    def test_critical_and_judge_source_errors_are_preserved(self):
        live, judged = fixture(1)
        candidates = [r for r in judged if r["variant"] == "candidate"]
        candidates[0]["critical"] = True
        candidates[1]["judge_error"] = "judge unavailable"
        candidates[2]["source_validation_error"] = "source changed"
        arm = compare_records(live, judged)["arms"]["candidate"]
        self.assertEqual(arm["critical"], 1)
        self.assertEqual(arm["errors"], 2)
        self.assertEqual(arm["error_counts"]["judge_error"], 1)
        self.assertEqual(arm["error_counts"]["source_validation_error"], 1)
        self.assertEqual(arm["pass"], 0)
        self.assertFalse(arm["gates"]["no_critical"])

    def test_duplicate_drop_extra_missing_main_and_answer_mismatch_rejected(self):
        mutations = {
            "live_duplicate": lambda l, j: l["records"].append(copy.deepcopy(l["records"][0])),
            "judge_duplicate": lambda l, j: j.append(copy.deepcopy(j[0])),
            "judge_drop": lambda l, j: j.pop(),
            "answer": lambda l, j: j[0].update(answer="synthetic answer "),
            "live_extra": lambda l, j: l["records"].append({**l["records"][0], "id": "extra"}),
            "main_controls": lambda l, j: l["arms"]["main"].update(policy="changed"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                live, judged = fixture(1)
                mutate(live, judged)
                with self.assertRaises(ValueError):
                    compare_records(live, judged)
        for variant in ("main", "candidate"):
            live, judged = fixture(1)
            live["records"] = [r for r in live["records"] if not (r["variant"] == variant and r["rep"] == 2)]
            judged = [r for r in judged if not (r["variant"] == variant and r["rep"] == 2)]
            with self.assertRaises(ValueError):
                compare_records(live, judged)
        live, judged = fixture(1)
        live["records"] = [r for r in live["records"] if r["variant"] == "main"]
        judged = [r for r in judged if r["variant"] == "main"]
        with self.assertRaises(ValueError):
            compare_records(live, judged)
        live, judged = fixture(1, ("candidate",))
        with self.assertRaises(ValueError):
            compare_records(live, judged)

    def test_round_and_grade_validation_never_regrades(self):
        live, judged = fixture(1)
        for rounds in (1, 2, 4, True, 3.0):
            with self.subTest(rounds=rounds), self.assertRaises(ValueError):
                compare_records(live, judged, rounds=rounds)
        for field, value in (("pass", 1), ("critical", None)):
            broken = copy.deepcopy(judged)
            broken[0][field] = value
            with self.assertRaises(ValueError):
                compare_records(live, broken)
        judged[0].update({"pass": True, "judge_error": "failed"})
        before = copy.deepcopy(judged)
        with self.assertRaises(ValueError):
            compare_records(live, judged)
        self.assertEqual(judged, before)

    def test_cli_outside_repo_exclusive_output_and_unchanged_inputs(self):
        live, judged = fixture(1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = [root / "live.json", root / "judged.json"]
            for path, value in zip(sources, (live, judged)):
                path.write_text(json.dumps(value), encoding="utf-8")
            before = [path.read_bytes() for path in sources]
            output = root / "comparison.json"
            argv = ["--live", str(sources[0]), "--judged", str(sources[1]),
                    "--output", str(output)]
            self.assertEqual(main(argv), 0)
            result = json.loads(output.read_text())
            self.assertEqual(len(result["input_sha256"]), 2)
            existing = output.read_bytes()
            with patch("sys.stderr"), self.assertRaises(SystemExit):
                main(argv)
            self.assertEqual(output.read_bytes(), existing)
            self.assertEqual([path.read_bytes() for path in sources], before)
            argv[-1] = str(sources[0])
            with patch("sys.stderr"), self.assertRaises(SystemExit):
                main(argv)
            self.assertEqual([path.read_bytes() for path in sources], before)
            argv[-1] = str(Path(__file__).parent / "private-output.json")
            with patch("sys.stderr"), self.assertRaises(SystemExit):
                main(argv)
            self.assertFalse(Path(argv[-1]).exists())

    def test_cli_refuses_input_changed_during_analysis(self):
        live, judged = fixture(1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live_path, judged_path = root / "live.json", root / "judged.json"
            live_path.write_text(json.dumps(live), encoding="utf-8")
            judged_path.write_text(json.dumps(judged), encoding="utf-8")
            output = root / "comparison.json"

            def changed_input(*args):
                result = compare_records(*args)
                judged_path.write_text("[]", encoding="utf-8")
                return result

            with patch("compare_followup.compare_records", changed_input), \
                    patch("sys.stderr"), self.assertRaises(SystemExit):
                main(["--live", str(live_path), "--judged", str(judged_path),
                      "--output", str(output)])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

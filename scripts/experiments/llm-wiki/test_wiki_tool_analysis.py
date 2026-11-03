"""Synthetic preregistered thresholds and telemetry accounting boundaries."""

import copy
import unittest

from wiki_tool_analysis import ARMS, WIKI_ARMS, analyze


def fixture():
    live, judged = [], []
    for arm in ARMS:
        for number in range(32):
            for rep in range(3):
                key = {"id": f"question-{number:02d}", "rep": rep, "variant": arm}
                live.append({
                    **key, "answer": "synthetic answer", "error": None,
                    "latency": {"first_text_ms": 1000},
                    "llm_calls": [{"kind": "generate", "phase": "answer", "usage": {"input_tokens": 999}}],
                    "usage": [{"phase": "answer", "usage": {"input_tokens": 100}}],
                    "wiki_selection": {"selected_page_ids": ["page-00001"]},
                    "wiki_selection_ms": 20,
                    "embedding_calls_during_request": 0,
                })
                judged.append({**key, "answer": "synthetic answer", "pass": False, "critical": False})
    return {"records": live, "arms": {arm: {} for arm in ARMS}}, judged


def rows(data, arm):
    source = data["records"] if isinstance(data, dict) else data
    return [row for row in source if row["variant"] == arm]


def pass_first(judged, arm, count):
    for row in rows(judged, arm)[:count]:
        row["pass"] = True


def get(data, arm, number=0, rep=0):
    return next(row for row in rows(data, arm)
                if row["id"] == f"question-{number:02d}" and row["rep"] == rep)


class WikiToolAnalysisTests(unittest.TestCase):
    def test_gain_six_is_insufficient_but_seven_passes(self):
        for count in (6, 7):
            with self.subTest(count=count):
                live, judged = fixture()
                pass_first(judged, "wiki_tool", count)
                result = analyze(live, judged)
                arm = result["arms"]["wiki_tool"]
                self.assertEqual(arm["delta_pass_vs_qa_full"], count)
                self.assertEqual(arm["quality_gates"]["gain_more_than_six"], count > 6)
                self.assertEqual(arm["worthy_to_continue"], count > 6)
                self.assertEqual(set(result["worthy_to_continue"]), {"wiki_tool"})

    def test_gain_is_against_qa_full_even_when_main_is_weaker(self):
        live, judged = fixture()
        pass_first(judged, "qa_full", 8)
        pass_first(judged, "wiki_tool", 14)
        result = analyze(live, judged)
        arm = result["arms"]["wiki_tool"]
        self.assertEqual(arm["delta_pass_vs_qa_full"], 6)
        self.assertFalse(arm["worthy_to_continue"])
        self.assertIn("wiki pass minus qa_full pass", result["policy"]["gain"])
        get(judged, "wiki_tool", number=4, rep=2)["pass"] = True
        arm = analyze(live, judged)["arms"]["wiki_tool"]
        self.assertEqual(arm["delta_pass_vs_qa_full"], 7)
        self.assertTrue(arm["worthy_to_continue"])

    def test_main_noise_seven_requires_gain_eight(self):
        for count in (7, 8):
            with self.subTest(count=count):
                live, judged = fixture()
                pass_first(judged, "main_noise", 7)
                pass_first(judged, "wiki_tool", count)
                result = analyze(live, judged)
                self.assertEqual(result["main_noise"]["pass_label_disagreement_count"], 7)
                self.assertEqual(result["arms"]["wiki_tool"]["worthy_to_continue"], count == 8)

    def test_noise_counts_disagreement_pairs_rather_than_net_gain(self):
        live, judged = fixture()
        pass_first(judged, "main", 3)
        for row in rows(judged, "main_noise")[3:6]:
            row["pass"] = True
        result = analyze(live, judged)
        self.assertEqual(result["main_noise"]["pass_label_disagreement_count"], 6)
        self.assertEqual(result["arms"]["main"]["pass"], result["arms"]["main_noise"]["pass"])

    def test_shared_critical_is_not_new_but_other_clean_base_blocks(self):
        live, judged = fixture()
        for arm in ("main", "qa_full", "wiki_tool"):
            get(judged, arm, number=31)["critical"] = True
        pass_first(judged, "wiki_tool", 8)
        result = analyze(live, judged)["arms"]["wiki_tool"]
        self.assertTrue(result["worthy_to_continue"])
        self.assertEqual(result["critical"], 1)
        for base in ("main", "qa_full"):
            self.assertEqual(result["regressions_vs"][base]["new_critical_questions"], [])
        get(judged, "qa_full", number=31)["critical"] = False
        result = analyze(live, judged)["arms"]["wiki_tool"]
        self.assertFalse(result["worthy_to_continue"])
        self.assertEqual(result["regressions_vs"]["main"]["new_critical_questions"], [])
        self.assertEqual(result["regressions_vs"]["qa_full"]["new_critical_questions"], [
            {"id": "question-31", "critical_reps": [0]},
        ])

    def test_stable_regression_requires_two_wiki_failures_against_either_base(self):
        for base in ("main", "qa_full"):
            live, judged = fixture()
            for rep in range(3):
                get(judged, base, number=31, rep=rep)["pass"] = True
            for rep in (0, 1):
                get(judged, "wiki_tool", number=31, rep=rep)["pass"] = True
            arm = analyze(live, judged)["arms"]["wiki_tool"]
            self.assertEqual(arm["regressions_vs"][base]["stable_pass_regressions"], [])
            get(judged, "wiki_tool", number=31, rep=1)["pass"] = False
            arm = analyze(live, judged)["arms"]["wiki_tool"]
            self.assertEqual(arm["regressions_vs"][base]["stable_pass_regressions"], [
                {"id": "question-31", "failing_reps": [1, 2]},
            ])

    def test_provider_usage_events_sum_retries_and_split_phases(self):
        live, judged = fixture()
        row = get(live, "wiki_tool")
        row["llm_calls"] = [
            {"kind": "generate", "phase": "selection", "usage": {"input_tokens": 500}},
            {"kind": "generate", "phase": "answer", "usage": {"input_tokens": 800}},
        ]
        row["usage"] = [
            {"phase": "selection", "usage": {"input_tokens": 20}},
            {"phase": "selection", "usage": {"input_tokens": 30}},
            {"phase": "answer", "usage": {"input_tokens": 100}},
        ]
        result = analyze(live, judged)["arms"]["wiki_tool"]
        telemetry = result["telemetry"][0]
        self.assertEqual(telemetry["input_tokens"], 150)
        self.assertEqual(telemetry["logical_llm_calls"], 2)
        self.assertEqual(telemetry["phases"]["selection"]["input_tokens"], 50)
        self.assertEqual(telemetry["phases"]["answer"]["input_tokens"], 100)
        self.assertEqual(telemetry["usage_event_count"], 3)
        self.assertEqual(result["input_tokens"]["median"], 100)
        self.assertEqual(result["phases"]["selection"]["logical_llm_calls"]["median"], 0)

    def test_missing_tokens_are_unknown_not_zero_or_partial_sums(self):
        for usage in (None, {"input_tokens": None}, {"input_tokens": True}):
            live, judged = fixture()
            row = get(live, "wiki_tool")
            row["usage"] = [
                {"phase": "answer", "usage": {"input_tokens": 100}},
                {"phase": "answer", "usage": usage},
            ]
            result = analyze(live, judged)["arms"]["wiki_tool"]
            self.assertIsNone(result["telemetry"][0]["input_tokens"])
            self.assertEqual(result["token_missing"], 1)
            self.assertEqual(result["input_tokens"]["missing"], 1)
            self.assertEqual(result["input_tokens"]["median"], 100)

    def test_absent_usage_events_do_not_fall_back_to_logical_call_tokens(self):
        live, judged = fixture()
        get(live, "wiki_tool")["usage"] = []
        arm = analyze(live, judged)["arms"]["wiki_tool"]
        self.assertIsNone(arm["telemetry"][0]["input_tokens"])
        self.assertEqual(arm["token_missing"], 1)

    def test_missing_usage_collection_counts_one_expected_call_not_empty_phases(self):
        live, judged = fixture()
        get(live, "wiki_tool").pop("usage")
        arm = analyze(live, judged)["arms"]["wiki_tool"]
        self.assertIsNone(arm["telemetry"][0]["input_tokens"])
        self.assertEqual(arm["token_missing"], 1)
        self.assertEqual(arm["telemetry"][0]["phases"]["selection"]["token_missing"], 0)

    def test_unknown_logical_call_count_does_not_erase_measured_provider_tokens(self):
        live, judged = fixture()
        get(live, "wiki_tool").pop("llm_calls")
        telemetry = analyze(live, judged)["arms"]["wiki_tool"]["telemetry"][0]
        self.assertIsNone(telemetry["logical_llm_calls"])
        self.assertEqual(telemetry["input_tokens"], 100)

    def test_errors_and_missing_timings_are_not_fast_measurements(self):
        live, judged = fixture()
        row = get(live, "wiki_tool")
        row["error"] = "synthetic execution failure"
        row["latency"]["first_text_ms"] = 0
        get(live, "wiki_tool", rep=1)["latency"] = None
        get(live, "main", rep=2)["latency"]["first_text_ms"] = None
        result = analyze(live, judged)
        arm = result["arms"]["wiki_tool"]
        self.assertEqual(arm["absolute_first_text_ms"]["measured"], 94)
        self.assertEqual(arm["absolute_first_text_ms"]["median"], 1000)
        pairs = arm["paired_first_text"]["main"]
        self.assertEqual(pairs["measured_pairs"], 93)
        self.assertEqual(len(pairs["missing_pairs"]), 3)
        self.assertFalse(pairs["complete"])
        self.assertEqual(pairs["median_added_ms"], 0)
        self.assertIsNone(arm["telemetry"][0]["selection_ms"])
        self.assertGreater(result["main_self_variation"]["signed_delta_ms"]["missing"], 0)

    def test_latency_is_descriptive_and_does_not_apply_legacy_200ms_gate(self):
        live, judged = fixture()
        pass_first(judged, "wiki_tool", 8)
        for row in rows(live, "wiki_tool"):
            row["latency"]["first_text_ms"] = 12000
        result = analyze(live, judged)["arms"]["wiki_tool"]
        self.assertEqual(result["paired_first_text"]["main"]["p90_added_ms"], 11000)
        self.assertTrue(result["worthy_to_continue"])
        self.assertNotIn("latency", result["quality_gates"])

    def test_page_selection_telemetry_and_embedding_zero_invariant(self):
        live, judged = fixture()
        pass_first(judged, "wiki_tool", 8)
        row = get(live, "wiki_tool")
        row["wiki_selection"]["selected_page_ids"] = ["page-00003", "page-00001"]
        row["wiki_selection_ms"] = 25
        before = copy.deepcopy((live, judged))
        result = analyze(live, judged)
        self.assertEqual((live, judged), before)
        telemetry = result["arms"]["wiki_tool"]["telemetry"][0]
        self.assertEqual(telemetry["selected_page_ids"], ["page-00003", "page-00001"])
        self.assertEqual(telemetry["selection_ms"], 25)
        self.assertTrue(result["arms"]["wiki_tool"]["embedding_zero"])
        row["embedding_calls_during_request"] = 1
        arm = analyze(live, judged)["arms"]["wiki_tool"]
        self.assertTrue(arm["quality_pass"])
        self.assertFalse(arm["embedding_zero"])
        self.assertFalse(arm["worthy_to_continue"])

    def test_keeps_three_original_pass_and_critical_labels_per_question(self):
        live, judged = fixture()
        get(judged, "wiki_tool", rep=1)["pass"] = True
        get(judged, "wiki_tool", rep=2)["critical"] = True
        original = analyze(live, judged)["per_question"][0]["arms"]["wiki_tool"]
        self.assertEqual(original["pass"], [False, True, False])
        self.assertEqual(original["critical"], [False, False, True])

    def test_exact_domain_shape_and_complete_pairing_required(self):
        self.assertEqual(ARMS, ("main", "main_noise", "qa_full", "wiki_tool"))
        self.assertEqual(WIKI_ARMS, ("wiki_tool",))
        live, judged = fixture()
        live["records"] = [r for r in live["records"] if r["variant"] != "qa_full"]
        judged = [r for r in judged if r["variant"] != "qa_full"]
        live["arms"].pop("qa_full")
        with self.assertRaises(ValueError):
            analyze(live, judged)
        live, judged = fixture()
        live["records"] = [r for r in live["records"] if r["id"] != "question-31"]
        judged = [r for r in judged if r["id"] != "question-31"]
        with self.assertRaises(ValueError):
            analyze(live, judged)
        live, judged = fixture()
        live["records"].pop()
        judged.pop()
        with self.assertRaises(ValueError):
            analyze(live, judged)


if __name__ == "__main__":
    unittest.main()

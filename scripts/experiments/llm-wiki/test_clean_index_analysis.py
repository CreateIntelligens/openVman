"""Identical-control prompt identity and judge-noise diagnostics."""

import unittest

from clean_index_analysis import analyze, prompt_signature
from test_compare_followup import fixture


class CleanIndexAnalysisTests(unittest.TestCase):
    def fixture(self):
        live, judged = fixture(1, ('main', 'main_noise', 'raw_multi'))
        for row in live['records']:
            row['prompt_messages'] = [{'role': 'user', 'content': 'synthetic'}]
        return live, judged

    def test_same_answer_grade_disagreement_is_retained(self):
        live, judged = self.fixture()
        next(r for r in judged if r['variant'] == 'main_noise')['pass'] = True
        result = analyze(live, judged)
        self.assertEqual(result['main_noise']['pass_disagreement_pairs'], 1)
        self.assertEqual(len(result['main_noise']['same_answer_grade_disagreements']), 1)
        self.assertEqual(result['absolute_first_text']['main']['median_ms'], 1000)

    def test_prompt_drift_invalidates_noise_control(self):
        live, judged = self.fixture()
        live['records'][-4]['prompt_messages'] = []
        with self.assertRaises(ValueError):
            analyze(live, judged)

    def test_only_request_clock_time_can_differ(self):
        a = [{'role': 'system', 'content': 'current_time: 2026-11-02 12:01:02 CST'}]
        b = [{'role': 'system', 'content': 'current_time: 2026-11-02 12:02:03 CST'}]
        self.assertEqual(prompt_signature(a), prompt_signature(b))
        b[0]['content'] = 'current_time: 2026-11-03 12:02:03 CST'
        self.assertNotEqual(prompt_signature(a), prompt_signature(b))

    def test_second_main_control_cannot_hide_consistent_candidate_failure(self):
        live, judged = self.fixture()
        for row in judged:
            if row['variant'] == 'main_noise':
                row['pass'] = True
        result = analyze(live, judged)
        self.assertTrue(result['arms']['raw_multi']['gates']['no_regression'])
        self.assertEqual(result['main_noise']['secondary_baseline_regressions']['raw_multi'],
                         [{'id': 'question-0', 'failing_reps': [0, 1, 2]}])

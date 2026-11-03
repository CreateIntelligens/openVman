"""Freeze new critical attribution, stable regressions and noise-based timing."""

from copy import deepcopy
import unittest

from qa_full_evaluation import ARMS, evaluate, length_bin
from test_compare_followup import fixture, set_pass


class QaFullEvaluationTests(unittest.TestCase):
    def data(self):
        live, judged = fixture(2, ('main', 'qa_full'))
        live['arms'] = deepcopy(ARMS)
        for row in live['records']:
            row['read_timing'] = {'knowledge_ms': 100}
        return live, judged

    def run_eval(self, live, judged):
        return evaluate(live, judged,
            {'retrieval_p90_added_ms': 20, 'first_text_p90_added_ms': 700},
            {'question-0': 'short', 'question-1': 'long'})

    def test_shared_flags_are_separate_but_candidate_only_flag_blocks(self):
        live, grades = self.data()
        for row in grades:
            if row['id'] == 'question-0' or row['variant'] == 'qa_full':
                row['critical'] = True
        result = self.run_eval(live, grades)
        self.assertEqual([r['id'] for r in result['new_critical']], ['question-1'])
        self.assertEqual([r['id'] for r in result['main_existing_critical']], ['question-0'])
        self.assertFalse(result['eligible_for_dev'])

    def test_single_miss_is_not_stable_regression_but_two_are(self):
        live, grades = self.data()
        set_pass(grades, 'main', {'question-0'})
        set_pass(grades, 'qa_full', {'question-0'}, [0, 1])
        self.assertFalse(self.run_eval(live, grades)['stable_regressions'])
        next(r for r in grades if r['id'] == 'question-0'
             and r['variant'] == 'qa_full' and r['rep'] == 1)['pass'] = False
        self.assertEqual(len(self.run_eval(live, grades)['stable_regressions']), 1)

    def test_700ms_noise_boundary_replaces_200ms_gate(self):
        live, grades = self.data()
        for row in live['records']:
            if row['variant'] == 'qa_full':
                row['latency']['first_text_ms'] = 1700
                row['read_timing']['knowledge_ms'] = 120
        self.assertTrue(self.run_eval(live, grades)['eligible_for_dev'])
        live['records'][-1]['latency']['first_text_ms'] = 1701
        self.assertFalse(self.run_eval(live, grades)['latency']['first_text_gate'])

    def test_bins_count_source_answer_codepoints(self):
        for length, expected in [(100, '0-100'), (101, '101-300'), (300, '101-300'),
                                 (301, '301-800'), (800, '301-800'), (801, '801+')]:
            self.assertEqual(length_bin('字' * length), expected)

    def test_other_candidates_cannot_enter_blind_trial(self):
        live, grades = self.data()
        live['arms']['k5'] = {}
        with self.assertRaises(ValueError):
            self.run_eval(live, grades)

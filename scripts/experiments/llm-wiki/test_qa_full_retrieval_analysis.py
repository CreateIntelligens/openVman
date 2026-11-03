"""Report dropped literal hits and sparse long-QA coverage without hiding noise."""

import unittest

from qa_full_retrieval_analysis import summarize


class RetrievalAnalysisTests(unittest.TestCase):
    def data(self):
        return {'questions': [{'id': 'a', 'q': 'q', 'set': 'kb', 'lang': 'zh', 'expect': 'target'},
                              {'id': 'n', 'q': 'n', 'set': 'noise', 'lang': 'en', 'expect': None}],
                'records': [{'id': cid, 'variant': arm, 'retrieval_ms': 10,
                    'result': {'results': [{'text': 'target'}] if (cid, arm) in
                               [('a', 'main'), ('n', 'qa_full')] else [], 'related': []}}
                    for cid in ['a', 'n'] for arm in ['main', 'qa_full']],
                'qa_inventory': [{'chunk_id': 'short', 'text': 'target', 'answer_chars': 50},
                                 {'chunk_id': 'long', 'text': 'other', 'answer_chars': 900}],
                'row_count': 10, 'readonly_check': {'changed_paths': []}, 'config_unchanged': True}

    def test_lost_hit_added_noise_and_uncovered_long_bin_visible(self):
        result = summarize(self.data())
        self.assertEqual(result['groups']['all']['lost_ids'], ['a'])
        self.assertEqual(result['groups']['all']['added_noise_ids'], ['n'])
        self.assertFalse(result['no_lost_hit_or_added_noise'])
        self.assertEqual(result['qa_inventory_length_bins']['801+'], 1)
        self.assertNotIn('801+', result['covered_qa_rows_length_bins'])

    def test_missing_and_duplicate_rows_rejected(self):
        for duplicate in (False, True):
            data = self.data()
            if duplicate:
                data['records'].append(data['records'][0])
            else:
                data['records'].pop()
            with self.assertRaises(ValueError):
                summarize(data)

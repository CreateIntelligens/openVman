"""Only QA vectors may differ in the production-hybrid vector factor."""

import copy
import unittest

from hybrid_controls import ARMS, full_qa_rows, row_digest


class HybridControlTests(unittest.TestCase):
    def test_factors_do_not_combine_changes(self):
        self.assertEqual(ARMS['main'], {})
        for arm in list(ARMS.values())[1:]:
            self.assertEqual(sum(bool(arm.get(k)) for k in
                                 ('qa_full', 'top_k', 'no_context')), 1)

    def test_full_text_only_for_qa_and_preserve_all_other_columns(self):
        rows = [
            {'chunk_id': 'a', 'text': '主題：測試\n問題：問\n回答：完整答案',
             'metadata': '{"question":"問","title":"測試"}', 'vector': [1., 0.]},
            {'chunk_id': 'b', 'text': 'ordinary text', 'metadata': '{}', 'vector': [1., 0.]},
        ]
        original = copy.deepcopy(rows)
        seen = []
        def encode(texts, **kwargs):
            seen.extend(texts)
            return [[0., 1.]], {'identity': 'synthetic'}, {}
        new, changed = full_qa_rows(rows, encode, 'synthetic')
        self.assertEqual(changed, [0])
        self.assertEqual(seen, [rows[0]['text']])
        self.assertEqual(new[1], rows[1])
        self.assertEqual(new[0]['vector'], [0., 1.])
        self.assertEqual(rows, original)
        self.assertEqual(row_digest(rows, exclude_vector=True),
                         row_digest(new, exclude_vector=True))

    def test_wrong_identity_or_incomplete_batch_is_rejected(self):
        rows = [{'text': '問題：問\n回答：答', 'metadata': {'question': '問'}, 'vector': [1.]}]
        for response in (([[1.]], {'identity': 'wrong'}, {}),
                         ([], {'identity': 'synthetic'}, {})):
            with self.subTest(response=response), self.assertRaises(ValueError):
                full_qa_rows(rows, lambda *a, **k: response, 'synthetic')

    def test_invalid_vector_cannot_enter_shadow_index(self):
        rows = [{'text': '問題：問\n回答：答', 'metadata': {'question': '問'}, 'vector': [1., 0.]}]
        for vector in ([float('nan'), 0.], [float('inf'), 0.], [2., 0.], [1.]):
            with self.subTest(vector=vector), self.assertRaises(ValueError):
                full_qa_rows(rows, lambda *a, **k: ([vector], {'identity': 'synthetic'}, {}),
                             'synthetic')

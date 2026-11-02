"""Reject drift in production-runner adapter before any live execution."""

import unittest

from hybrid_benchmark import hybrid_script, insert
from main_wiki_benchmark import SCRIPT


class HybridAdapterTests(unittest.TestCase):
    def test_script_compiles_and_contains_each_factor_once(self):
        value = hybrid_script(SCRIPT, '# synthetic controls')
        compile(value, '<synthetic-hybrid-runner>', 'exec')
        self.assertEqual(value.count('hybrid.ShadowIndex('), 1)
        self.assertIn('patch.object(hybrid_db, "get_table", selected_table)', value)
        self.assertIn('"hybrid_shadow":shadow.audit', value)
        self.assertIn('original_table(table_name, project_id, embedding_version)', value)

    def test_missing_or_duplicate_anchor_fail_closed(self):
        for base in ('', 'anchor anchor'):
            with self.assertRaises(ValueError):
                insert(base, 'anchor', 'replacement')

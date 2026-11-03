"""QA-only runner and original-rubric isolation without making model calls."""

import unittest
from unittest.mock import patch

from hybrid_benchmark import hybrid_script
from live_agent_stress import answering_cases
import main_wiki_benchmark as benchmark
import qa_full_blind
from qa_full_evaluation import ARMS
from qa_full_regression import SCRIPT, questions


class QaFullBlindTests(unittest.TestCase):
    def test_runner_selects_only_main_and_original_qa_full(self):
        with (patch.object(benchmark, 'main') as run,
              patch.object(benchmark, 'CLEAN_INDEX_ARMS', benchmark.CLEAN_INDEX_ARMS),
              patch.object(benchmark, 'SCRIPT', benchmark.SCRIPT)):
            qa_full_blind.main()
            self.assertEqual(benchmark.CLEAN_INDEX_ARMS, ARMS)
            run.assert_called_once()
            compile(benchmark.SCRIPT, '<qa-only-isolated-runner>', 'exec')

    def test_gold_and_source_group_metadata_never_reach_answering_process(self):
        original = [{'id': 'synthetic', 'q': 'question', 'history': [],
                     'gold': {'weight_3ph_kg': 123}, 'source_refs': ['synthetic'],
                     'source_image': 'synthetic.png', 'complete_model': 'ABC-123',
                     'required': ['private rubric'], 'status': 'draft_unrun'}]
        self.assertEqual(answering_cases(original),
                         [{'id': 'synthetic', 'q': 'question', 'history': []}])

    def test_existing_150_questions_and_no_k_sweep(self):
        values = questions()
        self.assertEqual(len(values), 150)
        self.assertEqual(sum(q['expect'] is not None for q in values), 141)
        self.assertEqual(sum(q['set'] == 'asr' for q in values), 57)
        self.assertIn("search(question['q'], top_k=3, threshold=.68)", SCRIPT)
        self.assertNotIn('top_k=5', SCRIPT)
        compile(SCRIPT, '<qa-only-retrieval-runner>', 'exec')

    def test_original_full_qa_candidate_bytes_are_used(self):
        source = (qa_full_blind.Path(qa_full_blind.__file__).parent
                  / 'hybrid_controls.py').read_text()
        assembled = hybrid_script(benchmark.SCRIPT, source)
        self.assertIn(repr(source), assembled)

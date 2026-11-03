"""The directory-tool adapter has no unguarded vector/FTS request path."""

from pathlib import Path
import unittest

from main_wiki_benchmark import SCRIPT
from wiki_tool_benchmark import ARMS, assemble


class WikiToolBenchmarkTests(unittest.TestCase):
    def test_compiles_with_only_declared_arms_and_embedding_guards(self):
        here=Path(__file__).parent
        value=assemble(SCRIPT,*[(here/n).read_text() for n in
            ['hybrid_controls.py','wiki_page_store.py','wiki_tool_runtime.py']],{},'fast-model')
        compile(value,'<assembled-wiki-tool>','exec')
        self.assertEqual(set(ARMS), {'main','main_noise','qa_full','wiki_tool'})
        self.assertIn('wiki_tool attempted query embedding',value)
        self.assertIn('wiki_tool attempted FTS',value)
        self.assertIn('allow_forced_knowledge_search=False, force_knowledge_search=False',value)
        self.assertIn('phase = "selection"',value)
        self.assertIn('reply.usage.as_dict()',value)

"""LLM, rather than local search, chooses complete pages; selector prose is excluded."""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from wiki_tool_runtime import answer_messages, select_pages


class WikiToolRuntimeTests(unittest.TestCase):
    def test_selected_full_page_preserved_without_selector_prose(self):
        session = SimpleNamespace(read_page_ids=['p1'], handle=Mock(return_value={
            'results': [{'text': 'full original page ' * 100}], 'related': []}))
        store = SimpleNamespace(catalog=lambda: [{'page_id': 'p1', 'title': 'A'}],
                                new_question=lambda: session)
        tool = SimpleNamespace(id='tc', name='read_wiki_page', arguments='{"page_id":"p1"}')
        generate = Mock(side_effect=[SimpleNamespace(model='same', tool_calls=[tool], content='SECRET SELECTOR PROSE'),
                                     SimpleNamespace(model='same', tool_calls=[], content='DONE')])
        result = select_pages('question', [], store, generate=generate, model='same',
            serialize_turn=lambda turn: {'role':'assistant','content':turn.content,'tool_calls':[]})
        messages = answer_messages([{'role':'system','content':'use search_knowledge'},
                                    {'role':'user','content':'question'}], result, store.catalog())
        self.assertNotIn('SECRET SELECTOR PROSE', json.dumps(messages))
        self.assertIn('full original page ' * 100, json.loads(messages[-1]['content'])['data']['results'][0]['text'])
        self.assertEqual(result['selected_page_ids'], ['p1'])
        self.assertTrue(all(call.kwargs['model_override']=='same' for call in generate.call_args_list))

    def test_no_page_is_recorded_without_fabricating_a_read(self):
        session = SimpleNamespace(read_page_ids=[], handle=Mock())
        store = SimpleNamespace(catalog=lambda: [],new_question=lambda:session)
        result = select_pages('unknown',[],store,generate=lambda *a,**k:SimpleNamespace(
            model='same',tool_calls=[],content='DONE'),model='same',serialize_turn=Mock())
        session.handle.assert_not_called()
        self.assertEqual(result['steps'][0]['name'],'wiki_selection')
        self.assertEqual(result['selected_page_ids'],[])

    def test_failure_after_a_read_preserves_original_partial_evidence(self):
        session = SimpleNamespace(read_page_ids=['p1'], handle=lambda args:{'results':[{'text':'complete'}]})
        store = SimpleNamespace(catalog=lambda:[{'page_id':'p1','title':'A'}],new_question=lambda:session)
        tc = SimpleNamespace(id='tc',name='read_wiki_page',arguments='{"page_id":"p1"}')
        generate = Mock(side_effect=[SimpleNamespace(model='same',content='',tool_calls=[tc]),RuntimeError('failed')])
        with self.assertRaises(RuntimeError) as caught:
            select_pages('q',[],store,generate=generate,model=None,serialize_turn=lambda turn:{'role':'assistant','content':''})
        self.assertEqual(len(caught.exception.partial_steps),1)
        self.assertEqual(caught.exception.partial_wiki_selection['selected_page_ids'],['p1'])

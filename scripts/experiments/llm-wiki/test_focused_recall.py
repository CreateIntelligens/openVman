"""Check source-unit admission and whole-record budget behavior."""

import copy
from pathlib import Path
import tempfile
import types
from threading import RLock
import unittest
from unittest.mock import patch

from focused_recall import (
    LexicalIndex,
    SearchRuntime,
    bounded_related,
    complete_records,
    exact_documents,
    unit_records,
)


class FocusedRecallTests(unittest.TestCase):
    def test_related_records_share_the_real_budget_and_are_never_cut(self):
        results = [{"text": "a" * 7508}]
        related = [{"text": "b" * 300}, {"text": "c" * 258}]
        selected = bounded_related(results, related)
        self.assertEqual(selected, related[:1])
        self.assertLessEqual(sum(len(row["text"]) for row in results + selected), 8000)
        self.assertEqual(bounded_related([{"text": "a" * 8000}], related), [])
        self.assertEqual(bounded_related(results, related, limit=1), [])
        self.assertEqual(bounded_related(results, results + related), related[:1])

    def test_cached_vectors_do_not_keep_a_newly_invisible_source(self):
        import numpy as np

        knowledge = types.ModuleType("tools.builtin.knowledge_tools")
        knowledge._search_one = lambda *a, **k: ([], None, None)
        helpers = types.ModuleType("tools.search_helpers")
        helpers.merge_search_results = lambda grouped, **kw: [r for _, rows in grouped for r in rows]
        helpers.normalize_query_list = lambda data: data["queries"]
        parent = types.ModuleType("tools")
        builtin = types.ModuleType("tools.builtin")
        builtin.knowledge_tools = knowledge
        runtime = SearchRuntime.__new__(SearchRuntime)
        runtime.lock, runtime.trace = RLock(), []
        runtime.np = np
        runtime.sections = [{"id":"s1","text":"supported original","slug":"topic",
                             "source_refs":["u1"]}]
        runtime.units = []
        runtime.vectors = {"wiki":np.asarray([[1.,0.]])}
        runtime._vector = lambda q: np.asarray([1.,0.])
        states = iter([(runtime.sections, []), ([], [{"id":"s1","reason":"disabled_source"}])])
        runtime._valid = lambda: next(states)
        runtime.formal = lambda *a,**k: {"results":[],"related":[]}
        runtime.gate = types.SimpleNamespace(
            merge_ranklists=lambda grouped, merge, limit: [r for _,rows in grouped for r in rows][:limit])
        with patch.dict("sys.modules", {"tools":parent,"tools.builtin":builtin,
                                        "tools.builtin.knowledge_tools":knowledge,
                                        "tools.search_helpers":helpers}):
            self.assertEqual(len(runtime.search(["q"],profile="safe_mixed")["results"]), 1)
            self.assertEqual(runtime.search(["q"],profile="safe_mixed")["results"], [])
        self.assertEqual(runtime.trace[-1]["rejected_sections"][0]["reason"], "disabled_source")

    def test_rewrite_rejects_new_numeric_facts_and_caches_valid_expansion(self):
        module = types.ModuleType("core.llm_client")
        parent = types.ModuleType("core")
        for proposed, accepted in ((['ZX-9.25聯絡資訊'], True),
                                   (['ZX-9.75聯絡資訊'], False),
                                   (['保證209天'], False)):
            calls = []
            def generate(messages, **kwargs):
                calls.append(messages)
                import json
                return types.SimpleNamespace(content=json.dumps({"queries":proposed}), model="fixture")
            module.generate_chat_turn = generate
            runtime = SearchRuntime.__new__(SearchRuntime)
            runtime.rewrite_cache = {}
            with patch.dict("sys.modules", {"core":parent,"core.llm_client":module}):
                result = runtime._rewrite(['ZX-9.25的聯絡資訊？'])
                self.assertEqual(bool(result['queries']), accepted)
                self.assertEqual(runtime._rewrite(['ZX-9.25的聯絡資訊？']), result)
                self.assertEqual(len(calls), 1)

    def test_lexical_recall_keeps_original_fact_and_cannot_return_invisible_unit(self):
        records = [{"id":"a","text":"醫療文件受理：週六至11:00。"},
                   {"id":"b","text":"門診：週六上午看診。"}]
        index = LexicalIndex(records)
        self.assertEqual(index.hits('週六醫療文件受理', {'a','b'})[0]['id'], 'a')
        self.assertEqual(index.hits('醫療文件受理', {'b'}), [])

    def test_exact_document_does_not_bypass_persona_disabled_or_multiple_subjects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"knowledge").mkdir()
            path = "knowledge/ZX-9.25.md"
            (root/path).write_text("# ZX-9.25\n三相滿載電流17A。")
            args = dict(root=root, persona="default", project="p", disabled=[], detector=lambda _: [])
            self.assertEqual(len(exact_documents(["ZX-9.25的電流？"], {path:["global"]}, **args)), 1)
            self.assertEqual(exact_documents(["ZX-9.25的電流？"], {path:["foreign"]}, **args), [])
            self.assertEqual(exact_documents(["ZX-9.25還是ZX-9.75？"], {path:["global"]}, **args), [])
            self.assertEqual(exact_documents(["ZX-9.25的電流？"], {path:["global"]}, **{**args,"disabled":[path]}), [])
            self.assertEqual(exact_documents(["ZX-9.25的電流？"], {path:["global"]}, **{**args,"detector":lambda _: ["instruction"]}), [])

    def setUp(self):
        self.source = {"u1": {"path": "knowledge/a.csv", "topic": "topic",
                              "text": "問題：流程？\n答覆：含附件須9工作天。", "question": "流程？"},
                       "blocked": {"path": "knowledge/a.csv", "topic": "topic", "text": "unadmitted"}}
        self.sections = [{"id": "s1", "source_refs": ["u1"], "source_paths": ["knowledge/a.csv"],
                          "project_id": "p", "persona_id": "default",
                          "text":self.source["u1"]["text"] + " [u1]"}]
        self.manifest = {"sources": {"knowledge/a.csv": {"refs": ["u1"], "sha256": "a" * 64}}}

    def test_unadmitted_units_never_enter_recall(self):
        before = copy.deepcopy(self.source)
        rows = unit_records(self.source, self.sections, self.manifest)
        self.assertEqual(len(rows), 1)
        self.assertIn("含附件須9工作天。", rows[0]["text"])
        self.assertEqual(rows[0]["source_refs"], ["u1"])
        self.assertEqual(rows[0]["source_hashes"], {"knowledge/a.csv": "a" * 64})
        self.assertEqual(self.source, before)

    def test_wrong_unit_path_or_ref_is_rejected(self):
        self.manifest["sources"]["knowledge/a.csv"]["refs"] = []
        with self.assertRaises(ValueError):
            unit_records(self.source, self.sections, self.manifest)

    def test_forged_unit_body_cannot_reuse_a_valid_ref_and_source_hash(self):
        self.source["u1"]["text"] = "已改為0工作天。"
        with self.assertRaisesRegex(ValueError, "Unit text differs"):
            unit_records(self.source, self.sections, self.manifest)

    def test_budget_never_cuts_conditions_or_table(self):
        rows = [{"text": "條件：包含附件才是9工作天。"}, {"text": "無附件為7天。"}]
        self.assertEqual(complete_records([rows], limit=5, char_budget=len(rows[1]["text"])-1), [])
        self.assertEqual(complete_records([rows], limit=5, char_budget=len(rows[1]["text"])), [rows[1]])

    def test_protected_primary_set_stays_before_new_unit_hits(self):
        primary = [{"text": "official " + str(i)} for i in range(5)]
        units = [{"text": "focused"}, {"text": primary[3]["text"]}]
        result = complete_records([primary, units], limit=10)
        self.assertEqual(result[:5], primary)
        self.assertEqual(len(result), 6)


if __name__ == "__main__":
    unittest.main()

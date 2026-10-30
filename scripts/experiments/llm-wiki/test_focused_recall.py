"""Check source-unit admission and whole-record budget behavior."""

import copy
import math
from pathlib import Path
import tempfile
import types
from threading import RLock
import unittest
from unittest.mock import Mock, patch

from focused_recall import (
    LexicalIndex,
    SearchRuntime,
    bounded_related,
    complete_records,
    exact_documents,
    terms,
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


class QueryVectorReuseTests(unittest.TestCase):
    def setUp(self):
        import numpy as np

        self.np = np
        self.encodings = []
        self.query_vectors = {"actual query": [0.6, 0.8], "other query": [1.0, 0.0]}
        self.embedder = types.ModuleType("memory.embedder")

        def encode(query, **kwargs):
            self.encodings.append((query, kwargs))
            return types.SimpleNamespace(
                version="fixture-version", vector=list(self.query_vectors[query]),
            )

        self.embedder.encode_query_with_fallback = encode
        self.knowledge = types.ModuleType("tools.builtin.knowledge_tools")

        def search_one(table, query, *args, **kwargs):
            route = encode(query, project_id="fixture", table_names=(table,))
            return [], route.version, route.vector

        self.knowledge._search_one = search_one
        helpers = types.ModuleType("tools.search_helpers")
        helpers.merge_search_results = lambda grouped, **kw: [
            r for _, rows in grouped for r in rows
        ]
        helpers.normalize_query_list = lambda data: data["queries"]
        builtin = types.ModuleType("tools.builtin")
        builtin.knowledge_tools = self.knowledge
        self.modules = {
            "memory": types.ModuleType("memory"),
            "memory.embedder": self.embedder,
            "tools": types.ModuleType("tools"),
            "tools.builtin": builtin,
            "tools.builtin.knowledge_tools": self.knowledge,
            "tools.search_helpers": helpers,
        }

    def runtime(self):
        runtime = SearchRuntime.__new__(SearchRuntime)
        runtime.np = self.np
        runtime.pid, runtime.persona = "fixture", "default"
        runtime.identity = "fixture-identity"

        def resolve(version):
            if version == "invalid-version":
                raise ValueError("Unknown fixture identity")
            if version == "missing-version":
                raise KeyError(version)
            return ("fixture-identity" if version == "fixture-version"
                    else "different-identity")

        runtime.cfg = types.SimpleNamespace(resolve_embedding_identity=resolve)
        runtime.lock, runtime.trace = RLock(), []
        runtime.query_cache = {}
        runtime.sections = [
            {"id": "s1", "slug": "one", "text": "first source", "source_refs": ["r1"]},
            {"id": "s2", "slug": "two", "text": "second source", "source_refs": ["r2"]},
        ]
        runtime.units = [
            {"id": "u1", "text": "first unit", "parent_ids": ["s1"]},
            {"id": "u2", "text": "second unit", "parent_ids": ["s2"]},
        ]
        runtime.vectors = {
            bank: self.np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=self.np.float32)
            for bank in ("wiki", "unit_full", "unit_question")
        }
        runtime._valid = lambda: (runtime.sections, [])
        runtime.gate = types.SimpleNamespace(
            merge_ranklists=lambda grouped, merge, limit: [
                row for _, rows in grouped for row in rows
            ][:limit],
        )

        def formal(*args, **kwargs):
            for query in kwargs["queries"]:
                self.knowledge._search_one("knowledge", query, 5, "default", "fixture")
            return {"results": [], "related": []}

        runtime.formal = formal
        return runtime

    def test_formal_reuse_preserves_hits_and_halves_query_encoder_calls(self):
        queries = ["actual query", "other query"]
        original, reused = self.runtime(), self.runtime()
        original._reuse_query_vector = lambda *args: None
        with patch.dict("sys.modules", self.modules):
            expected = original.search(queries, profile="safe_mixed")
            self.assertEqual(len(self.encodings), 4)
            self.encodings.clear()
            actual = reused.search(queries, profile="safe_mixed")
            self.assertEqual(len(self.encodings), 2)
            self.assertEqual(actual, expected)
            self.assertEqual(reused.trace, original.trace)
            for query in queries:
                for bank in reused.vectors:
                    valid = {"s1", "s2"} if bank == "wiki" else {"u1", "u2"}
                    self.assertEqual(
                        reused._hits(query, bank, valid, threshold=.60, limit=8),
                        original._hits(query, bank, valid, threshold=.60, limit=8),
                    )
            self.assertEqual(len(self.encodings), 2)

    def test_incompatible_candidates_do_not_pollute_cache_or_skip_encoding(self):
        for version, vector in (
            ("other-version", [1.0, 0.0]),
            ("invalid-version", [1.0, 0.0]),
            ("missing-version", [1.0, 0.0]),
            ("fixture-version", [1.0, 0.0, 0.0]),
            ("fixture-version", [[1.0, 0.0]]),
            ("fixture-version", [0.0, 0.0]),
            ("fixture-version", [float("nan"), 0.0]),
            ("fixture-version", [float("inf"), 0.0]),
            ("fixture-version", ["invalid", 0.0]),
        ):
            with self.subTest(version=version, vector=vector):
                runtime = self.runtime()
                runtime._reuse_query_vector("actual query", version, vector)
                self.assertEqual(runtime.query_cache, {})
                self.encodings.clear()
                with patch.dict("sys.modules", self.modules):
                    value = runtime._vector("actual query")
                self.assertEqual(len(self.encodings), 1)
                self.np.testing.assert_array_equal(
                    value, self.np.asarray([0.6, 0.8], dtype=self.np.float32),
                )

    def test_invalid_reuse_keeps_original_encoder_validation_failures(self):
        for version, vector, message in (
            ("other-version", [1.0, 0.0], "Query identity differs"),
            ("fixture-version", [0.0, 0.0], "Query is not normalized"),
        ):
            with self.subTest(version=version, vector=vector):
                runtime = self.runtime()
                runtime._reuse_query_vector("actual query", version, vector)
                self.embedder.encode_query_with_fallback = lambda *a, **kw: (
                    types.SimpleNamespace(version=version, vector=vector)
                )
                with patch.dict("sys.modules", self.modules):
                    with self.assertRaisesRegex(ValueError, message):
                        runtime._vector("actual query")
                self.assertEqual(runtime.query_cache, {})

    def test_formal_vector_is_bound_to_its_actual_query(self):
        runtime = self.runtime()

        def formal(*args, **kwargs):
            self.knowledge._search_one("knowledge", "other query", 5, "default", "fixture")
            return {"results": [], "related": []}

        runtime.formal = formal
        with patch.dict("sys.modules", self.modules):
            runtime.search(["actual query"], profile="safe_mixed")
        self.assertEqual([query for query, _ in self.encodings], ["other query", "actual query"])
        self.assertNotIn("other query", runtime.query_cache)
        self.np.testing.assert_array_equal(
            runtime.query_cache["actual query"],
            self.np.asarray([0.6, 0.8], dtype=self.np.float32),
        )

    def test_reuse_copies_vector_and_does_not_overwrite_an_existing_cache(self):
        runtime = self.runtime()
        vector = self.np.asarray([0.6, 0.8], dtype=self.np.float32)
        runtime._reuse_query_vector("actual query", "fixture-version", vector)
        vector[:] = [1.0, 0.0]
        runtime._reuse_query_vector("actual query", "other-version", [0.0, 1.0])
        runtime._reuse_query_vector("actual query", "fixture-version", [0.0, 1.0])
        self.np.testing.assert_array_equal(
            runtime.query_cache["actual query"],
            self.np.asarray([0.6, 0.8], dtype=self.np.float32),
        )
        self.assertFalse(runtime.query_cache["actual query"].flags.writeable)


class ControlledRecallTests(unittest.TestCase):
    def setUp(self):
        self.fixture = QueryVectorReuseTests()
        self.fixture.setUp()
        self.modules = self.fixture.modules

    def runtime(self):
        runtime = self.fixture.runtime()
        runtime.root = Path("/unused-fixture-workspace")
        runtime.personas_by_path, runtime.disabled = {}, []
        runtime.lexical = LexicalIndex(runtime.units)
        runtime._rewrite = Mock(return_value={"queries": [], "error": None})
        runtime.gate.canonical_source = lambda path: path
        runtime.gate.detect_instruction = lambda text: []
        for unit in runtime.units:
            unit.update(chunk_id=unit["id"], src="source_unit")
        formal = runtime.formal

        def with_results(*args, **kwargs):
            formal(*args, **kwargs)
            return {
                "results": [{"chunk_id": "p" + str(i), "path": "knowledge/p.md",
                             "text": "official " + str(i)}
                            for i in range(kwargs["top_k"])],
                "related": [],
            }

        runtime.formal = Mock(side_effect=with_results)
        return runtime

    def test_none_and_explicit_defaults_preserve_output_and_legacy_trace(self):
        omitted, explicit, controlled = self.runtime(), self.runtime(), self.runtime()
        with patch.dict("sys.modules", self.modules):
            expected = omitted.search(["actual query"], profile="focused_v2")
            self.assertEqual(
                explicit.search(["actual query"], profile="focused_v2", controls=None),
                expected,
            )
            self.assertEqual(explicit.trace, omitted.trace)
            self.assertNotIn("controls", omitted.trace[-1])
            self.assertEqual(
                controlled.search(["actual query"], profile="focused_v2", controls={}),
                expected,
            )
        trace = copy.deepcopy(controlled.trace[-1])
        self.assertEqual(trace.pop("controls"), {
            "formal_top_k": 5, "include_wiki": True,
            "include_units": True, "rewrite": True,
        })
        self.assertEqual(trace, omitted.trace[-1])
        self.assertEqual(expected["results"][:5], omitted._mark([
            {"chunk_id": "p" + str(i), "path": "knowledge/p.md",
             "text": "official " + str(i)} for i in range(5)
        ]))
        self.assertEqual(omitted.trace[-1]["selected_ids"],
                         ["p0", "p1", "p2", "p3", "p4", "u2", "wiki:s2"])

    def test_no_wiki_and_no_rewrite_skip_banks_and_model(self):
        runtime = self.runtime()
        runtime._hits = Mock(wraps=runtime._hits)
        runtime._rewrite.side_effect = AssertionError("Must not invoke query model")
        controls = {"formal_top_k": 3, "include_wiki": False, "rewrite": False}
        with patch.dict("sys.modules", self.modules):
            result = runtime.search(["actual query"], profile="focused_v2", controls=controls)
        runtime._rewrite.assert_not_called()
        self.assertTrue(runtime._hits.call_args_list)
        self.assertTrue(all(call.args[1] != "wiki" for call in runtime._hits.call_args_list))
        self.assertEqual(runtime.formal.call_args.kwargs["top_k"], 3)
        self.assertEqual(result["queries"], ["actual query"])
        self.assertFalse(any(row.get("src") == "wiki" for row in result["results"]))
        self.assertFalse(any(str(value).startswith("wiki:")
                             for value in runtime.trace[-1]["selected_ids"]))
        self.assertIsNone(runtime.trace[-1]["rewrite"])
        self.assertEqual(runtime.trace[-1]["controls"], {**controls, "include_units": True})
        controls["include_wiki"] = True
        self.assertFalse(runtime.trace[-1]["controls"]["include_wiki"])

    def test_no_units_skips_dense_lexical_and_exact_document_recall(self):
        runtime = self.runtime()
        runtime._hits = Mock(wraps=runtime._hits)
        runtime.lexical.hits = Mock(side_effect=AssertionError("Units disabled"))
        with patch.dict("sys.modules", self.modules), patch("focused_recall.exact_documents") as exact:
            result = runtime.search(["actual query"], profile="focused_v2",
                                    controls={"include_units": False, "rewrite": False})
        runtime.lexical.hits.assert_not_called()
        exact.assert_not_called()
        self.assertTrue(all(call.args[1] == "wiki" for call in runtime._hits.call_args_list))
        self.assertFalse(any(row.get("src") in ("source_unit", "exact_document")
                             for row in result["results"]))
        self.assertEqual(runtime.trace[-1]["unit_candidates"], [])

    def test_enabled_rewrite_expands_formal_queries_without_mutating_input(self):
        runtime = self.runtime()
        runtime._rewrite.return_value = {"queries": ["other query"], "error": None}
        queries = ["actual query"]
        with patch.dict("sys.modules", self.modules):
            result = runtime.search(queries, profile="focused_v2", controls={"rewrite": True})
        runtime._rewrite.assert_called_once_with(["actual query"])
        self.assertEqual(queries, ["actual query"])
        self.assertEqual(result["queries"], ["actual query", "other query"])
        self.assertEqual(runtime.formal.call_args.kwargs["queries"], result["queries"])
        self.assertEqual(runtime.trace[-1]["input_queries"], queries)

    def test_controls_do_not_return_units_after_source_is_disabled(self):
        runtime = self.runtime()
        runtime._valid = lambda: ([], [{"id": "s1", "reason": "disabled_source"}])
        with patch.dict("sys.modules", self.modules):
            result = runtime.search(["actual query"], profile="focused_v2",
                                    controls={"include_wiki": False, "rewrite": False})
        self.assertTrue(all(row["src"] == "production" for row in result["results"]))
        self.assertEqual(runtime.trace[-1]["unit_candidates"], [])
        self.assertEqual(runtime.trace[-1]["valid_units"], 0)
        self.assertEqual(runtime.trace[-1]["rejected_sections"][0]["reason"], "disabled_source")

    def test_controls_keep_complete_records_rank_order_and_shared_budget(self):
        runtime = self.runtime()
        for unit in runtime.units:
            unit["text"] *= 800
        exact_row = {"chunk_id": "exact:fixture", "text": "exact source", "src": "exact_document"}
        with patch.dict("sys.modules", self.modules), patch(
            "focused_recall.exact_documents", return_value=[exact_row],
        ):
            result = runtime.search(["actual query"], profile="focused_v2",
                                    controls={"rewrite": False})
        self.assertEqual(result["results"][0], exact_row)
        self.assertEqual([row["chunk_id"] for row in result["results"][1:6]],
                         ["p0", "p1", "p2", "p3", "p4"])
        self.assertLessEqual(sum(len(row["text"]) for row in result["results"] + result["related"]), 8000)
        self.assertFalse(any(row.get("src") == "source_unit" for row in result["results"]))

    def test_invalid_controls_are_rejected_before_retrieval(self):
        cases = [[], "invalid", {"unknown": True}, {"formal_top_k": True},
                 {"formal_top_k": 3.0}, {"formal_top_k": 4},
                 {"include_units": 0}, {"include_wiki": "false"}, {"rewrite": None}]
        with patch.dict("sys.modules", self.modules):
            for controls in cases:
                with self.subTest(controls=controls):
                    runtime = self.runtime()
                    with self.assertRaises(ValueError):
                        runtime.search(["actual query"], profile="focused_v2", controls=controls)
                    runtime.formal.assert_not_called()
                    runtime._rewrite.assert_not_called()
            for profile in ("safe_mixed", "safe_wide", "focused_v1"):
                with self.subTest(profile=profile), self.assertRaises(ValueError):
                    self.runtime().search(["actual query"], profile=profile, controls={})


class LexicalLengthTests(unittest.TestCase):
    def test_precomputed_lengths_preserve_original_scores_and_ranking_exactly(self):
        records = [
            {"id": "a", "text": "條件 甲流程 alpha alpha beta"},
            {"id": "b", "text": "條件 乙流程 beta gamma gamma gamma"},
            {"id": "c", "text": ""},
            {"id": "d", "text": "不可見條件 alpha"},
        ]
        index = LexicalIndex(records)
        valid = {"a", "b", "c"}
        for query in ("alpha beta gamma 條件流程", "beta beta", "不存在", ""):
            expected = []
            for record, counts in zip(index.records, index.counts):
                if record["id"] not in valid:
                    continue
                score = 0.0
                for token in set(terms(query)):
                    tf = counts.get(token, 0)
                    if tf:
                        idf = math.log(1 + (len(records)-index.df[token]+.5)/(index.df[token]+.5))
                        score += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * sum(counts.values()) / max(index.average, 1)))
                if score:
                    expected.append({**record, "_lexical_score": score, "_score": score,
                                     "retrieval_bank": "unit_lexical"})
            expected.sort(key=lambda row: -row["_lexical_score"])
            with self.subTest(query=query):
                self.assertEqual(index.hits(query, valid), expected[:8])
                self.assertEqual(index.hits(query, valid, limit=1), expected[:1])


if __name__ == "__main__":
    unittest.main()

"""Isolated pipeline routing tests without providers, embedders or services."""

import copy
from pathlib import Path
from threading import RLock
import types
import unittest
from unittest.mock import Mock, patch

from corpus_recall import PreparedIndex, merge_ranks, rank_hits
from pipeline_runtime import Runtime


def record(row_id, bank, *, refs=None, text=None):
    return {
        "id": row_id, "src": bank,
        "text": text if text is not None else "synthetic text " + row_id,
        "source_refs": ["source-a"] if refs is None else refs,
        "source_paths": ["knowledge/synthetic.md"],
    }


class PipelineRuntimeTests(unittest.TestCase):
    def setUp(self):
        helpers = types.ModuleType("tools.search_helpers")
        helpers.normalize_query_list = lambda data: list(dict.fromkeys(
            query for query in data["queries"] if isinstance(query, str) and query.strip()
        ))
        self.modules = {
            "tools": types.ModuleType("tools"),
            "tools.search_helpers": helpers,
        }
        patcher = patch.dict("sys.modules", self.modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runtime = Runtime.__new__(Runtime)
        self.runtime.trace = []
        self.runtime.records = {
            "raw": [record("raw-only", "raw")],
            "grouped": [record("grouped-only", "grouped")],
            "compiled": [record("compiled-only", "compiled")],
        }
        self.runtime.vectors = {bank: [[1., 0.]] for bank in self.runtime.records}
        self.runtime.compiled = copy.deepcopy(self.runtime.records["compiled"])
        self.runtime.helper = types.SimpleNamespace(
            rank_hits=Mock(wraps=rank_hits), merge_ranks=Mock(wraps=merge_ranks),
        )
        gate = types.SimpleNamespace(validate_sections=Mock(
            return_value=(copy.deepcopy(self.runtime.compiled), []),
        ))
        self.validator = types.SimpleNamespace(
            pid="synthetic-project", persona="synthetic-persona",
            root=Path("/synthetic-workspace"),
            disabled=["knowledge/disabled-synthetic.md"],
            personas_by_path={"knowledge/synthetic.md": ["global"]},
            payload={"source_manifest": {"sources": {"synthetic": {}}}},
            lock=RLock(), gate=gate,
            _valid=Mock(return_value=([
                {"id": "valid-original", "source_refs": ["source-a", "source-b"]},
            ], [])),
            _vector=Mock(return_value=[1., 0.]),
            _rewrite=Mock(return_value={"queries": ["rewritten query"], "error": None}),
            formal=Mock(side_effect=AssertionError("Formal search must not run")),
            graph=Mock(side_effect=AssertionError("Graph expansion must not run")),
        )
        self.runtime.validator = self.validator

    def assert_no_rescue_or_related(self, result, bank):
        self.assertEqual({row["src"] for row in result["results"]}, {bank})
        self.assertEqual(result["related"], [])
        self.assertEqual(result["citations"], [])
        self.validator.formal.assert_not_called()
        self.validator.graph.assert_not_called()

    def test_invalid_controls_cannot_silently_enable_online_work(self):
        for controls in ({"banks":[]}, {"banks":["missing"]},
                         {"banks":["raw", "raw"]},
                         {"banks":["raw"], "rewrite":"false"},
                         {"banks":["raw"], "multi":1},
                         {"banks":["raw"], "unknown":True}):
            with self.subTest(controls=controls), self.assertRaises(ValueError):
                self.runtime.search(["question"], controls)
        self.validator._rewrite.assert_not_called()
        self.validator._valid.assert_not_called()

    def test_raw_direct_uses_only_raw_and_first_query(self):
        result = self.runtime.search(["first query", "second query"], {"banks": ["raw"]})

        self.assertEqual(result["queries"], ["first query"])
        self.assertEqual([row["id"] for row in result["results"]], ["raw-only"])
        self.assert_no_rescue_or_related(result, "raw")
        self.validator._rewrite.assert_not_called()
        self.validator._vector.assert_called_once_with("first query")
        self.validator.gate.validate_sections.assert_not_called()
        self.assertEqual(self.runtime.helper.rank_hits.call_args.args[0],
                         self.runtime.records["raw"])

    def test_md_direct_never_adds_valid_original_rescue_or_grouped_sections(self):
        result = self.runtime.search(["first query", "second query"],
                                     {"banks": ["compiled"], "multi": False, "rewrite": False})

        self.assertEqual(result["queries"], ["first query"])
        self.assertEqual([row["id"] for row in result["results"]], ["compiled-only"])
        self.assert_no_rescue_or_related(result, "compiled")
        self.validator._rewrite.assert_not_called()
        self.assertEqual(self.runtime.helper.rank_hits.call_args.args[0],
                         self.runtime.records["compiled"])

    def test_raw_and_md_use_identical_ranking_function_and_controls(self):
        kwargs = []
        for bank in ("raw", "compiled"):
            result = self.runtime.search(["first query"], {"banks": [bank]})
            self.assertEqual(len(result["results"]), 1)
            call = self.runtime.helper.rank_hits.call_args
            kwargs.append({key: value for key, value in call.kwargs.items() if key != "diagnostics"})
            self.assertEqual(call.args[2], [1., 0.])
            self.assertEqual(call.args[3], {"source-a", "source-b"})
        self.assertEqual(kwargs, [
            {"top_k": 5, "threshold": .68, "char_budget": 8000},
            {"top_k": 5, "threshold": .68, "char_budget": 8000},
        ])

    def test_md_multi_keeps_two_queries_and_rrf_top_five_with_one_budget(self):
        records = [record(str(i), "compiled", text=str(i) * 1600) for i in range(7)]
        self.runtime.records["compiled"] = records
        self.runtime.vectors["compiled"] = [
            [.8, .6], [.6, .8], [.72, .6939740629158989],
            [.6939740629158989, .72], [.71, .7042016756583301],
            [.7042016756583301, .71], [.7071067811865476, .7071067811865476],
        ]
        self.runtime.compiled = copy.deepcopy(records)
        self.validator.gate.validate_sections.return_value = (copy.deepcopy(records), [])
        self.validator._vector.side_effect = lambda query: (
            [1., 0.] if query == "first query" else [0., 1.]
        )

        result = self.runtime.search(["first query", "second query"],
                                     {"banks": ["compiled"], "multi": True})

        self.assertEqual(result["queries"], ["first query", "second query"])
        self.assertEqual(self.validator._vector.call_count, 2)
        self.assertEqual(self.runtime.helper.rank_hits.call_count, 2)
        fusion = self.runtime.helper.merge_ranks.call_args
        self.assertEqual(fusion.kwargs, {"top_k": 5, "char_budget": 8000})
        expected = merge_ranks(fusion.args[0], top_k=5, char_budget=8000)
        self.assertEqual([row["id"] for row in result["results"]], [r["id"] for r in expected])
        self.assertEqual(len(result["results"]), 5)
        self.assertEqual(sum(len(row["text"]) for row in result["results"]), 8000)
        self.assertEqual(self.runtime.trace[-1]["selected_chars"], 8000)
        self.assertTrue(all("rrf_score" in row and "score" in row for row in result["results"]))
        self.assert_no_rescue_or_related(result, "compiled")
        self.validator._rewrite.assert_not_called()

    def test_rewrite_runs_only_when_explicitly_enabled(self):
        for controls in ({"banks": ["compiled"]},
                         {"banks": ["compiled"], "rewrite": False},
                         {"banks": ["compiled"], "multi": True, "rewrite": False}):
            self.runtime.search(["first query", "second query"], controls)
        self.validator._rewrite.assert_not_called()
        result = self.runtime.search(["first query", "second query"],
                                     {"banks": ["compiled"], "rewrite": True})
        self.validator._rewrite.assert_called_once_with(["first query"])
        self.assertEqual(result["queries"], ["first query", "rewritten query"])
        self.assertEqual(self.runtime.trace[-1]["input_queries"], ["first query"])

    def test_missing_one_valid_ref_rejects_entire_multi_source_compiled_row(self):
        self.runtime.records["compiled"][0]["source_refs"] = ["source-a", "source-b"]
        self.runtime.compiled = copy.deepcopy(self.runtime.records["compiled"])
        self.validator.gate.validate_sections.return_value = (copy.deepcopy(self.runtime.compiled), [])
        self.validator._valid.return_value = ([{"id": "valid", "source_refs": ["source-a"]}], [])

        result = self.runtime.search(["first query"], {"banks": ["compiled"]})

        self.assertEqual(result["results"], [])
        self.assertEqual(result["related"], [])
        diagnostic = self.runtime.trace[-1]["diagnostics"][0]
        self.assertEqual(diagnostic["invalid_ref_ids"], ["compiled-only"])

    def test_compiled_gate_receives_current_project_persona_sources_and_rejects(self):
        rejection = [{"id": "compiled-only", "reason": "source_modified"}]
        self.validator.gate.validate_sections.return_value = ([], rejection)

        result = self.runtime.search(["first query"], {"banks": ["compiled"]})

        self.validator.gate.validate_sections.assert_called_once_with(
            self.runtime.compiled, self.validator.payload["source_manifest"],
            project_id=self.validator.pid, persona_id=self.validator.persona,
            workspace_root=self.validator.root,
            disabled_paths=self.validator.disabled,
            current_source_personas=self.validator.personas_by_path,
        )
        self.assertEqual(result["results"], [])
        self.assertEqual(result["related"], [])
        self.assertEqual(self.runtime.trace[-1]["rejected_compiled"], rejection)
        self.validator.formal.assert_not_called()
        self.validator.graph.assert_not_called()

    def test_each_request_revalidates_original_sources_without_reusing_prior_admission(self):
        first = self.runtime.search(["first query"], {"banks": ["compiled"]})
        self.assertEqual(len(first["results"]), 1)
        self.validator._valid.return_value = ([], [{"id": "valid-original", "reason": "disabled"}])
        second = self.runtime.search(["first query"], {"banks": ["compiled"]})

        self.assertEqual(second["results"], [])
        self.assertEqual(second["related"], [])
        self.assertEqual(self.validator._valid.call_count, 2)
        self.assertEqual(self.runtime.trace[-1]["rejected_sections"],
                         [{"id": "valid-original", "reason": "disabled"}])

    def test_prepared_index_uses_current_source_gate_and_compiled_admission(self):
        self.runtime.indexes = {
            bank: PreparedIndex(rows, self.runtime.vectors[bank])
            for bank, rows in self.runtime.records.items()
        }
        first = self.runtime.search(["first query"], {"banks":["compiled"]})
        self.assertEqual([r["id"] for r in first["results"]], ["compiled-only"])
        self.validator.gate.validate_sections.return_value = ([], [{"reason":"modified"}])
        self.assertEqual(self.runtime.search(["first query"], {"banks":["compiled"]})["results"], [])
        self.validator._valid.return_value = ([], [{"reason":"disabled"}])
        self.assertEqual(self.runtime.search(["first query"], {"banks":["raw"]})["results"], [])
        self.runtime.helper.rank_hits.assert_not_called()

    def test_empty_normalized_query_fails_before_any_retrieval(self):
        with self.assertRaisesRegex(ValueError, "actual runtime query"):
            self.runtime.search(["", "  "], {"banks": ["compiled"]})
        self.validator._valid.assert_not_called()
        self.validator._vector.assert_not_called()
        self.validator._rewrite.assert_not_called()


if __name__ == "__main__":
    unittest.main()

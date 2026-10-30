"""Synthetic corpus parity, provenance, vector and complete-record checks."""

import copy
import math
import unittest

from corpus_recall import build_corpora, merge_ranks, rank_hits


def row(row_id, text=None, refs=None):
    refs = ["ref-a"] if refs is None else refs
    return {"id": row_id, "text": text if text is not None else "text:" + row_id,
            "source_refs": refs, "source_paths": ["knowledge/synthetic.md"]}


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.sources = {
            "ref-a": {"text": "  原文\n含條件：僅週一。  ", "topic": "主題甲",
                      "path": "knowledge/synthetic.md"},
            "ref-b": {"text": "完整原文二。", "topic": "主題乙",
                      "path": "knowledge/synthetic-b.md"},
        }
        self.sections = [{
            "id": "section-a", "text": "完整既有MD。\n含例外。", "title": "既有主題",
            "source_refs": ["ref-a", "ref-b"],
            "source_paths": ["knowledge/synthetic.md", "knowledge/synthetic-b.md"],
            "source_hashes": {"knowledge/synthetic.md": "a" * 64},
        }]

    def test_build_preserves_complete_text_topic_and_source_mapping(self):
        before_sources, before_sections = copy.deepcopy(self.sources), copy.deepcopy(self.sections)
        corpora = build_corpora(self.sources, self.sections)
        self.assertEqual(len(corpora["raw"]), 2)
        self.assertEqual(corpora["md"], self.sections)
        for ref, source in self.sources.items():
            raw = next(r for r in corpora["raw"] if r["id"] == "raw:" + ref)
            self.assertEqual(raw["text"], source["text"])
            self.assertEqual(raw["topic"], source["topic"])
            self.assertEqual(raw["title"], source["topic"])
            self.assertEqual(raw["source_refs"], [ref])
            self.assertEqual(raw["source_paths"], [source["path"]])
        corpora["md"][0]["source_refs"].clear()
        corpora["raw"][0]["text"] = "changed"
        self.assertEqual(self.sources, before_sources)
        self.assertEqual(self.sections, before_sections)

    def test_missing_section_id_is_stable_and_unknown_ref_or_wrong_path_rejected(self):
        section = copy.deepcopy(self.sections[0])
        section.pop("id")
        self.assertEqual(build_corpora(self.sources, [section])["md"][0]["id"], "md:0")
        for key, value in (("source_refs", ["unknown"]),
                           ("source_paths", ["knowledge/synthetic.md"])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                build_corpora(self.sources, [{**self.sections[0], key: value}])

    def test_same_algorithm_and_defaults_apply_to_raw_and_md(self):
        source_text = "條件與例外保留。"
        sources = {"ref-a": {"text": source_text, "topic": "topic",
                              "path": "knowledge/synthetic.md"}}
        corpora = build_corpora(sources, [row("md-a", source_text)])
        outputs = [rank_hits(corpora[kind], [[1.0, 0.0]], [1.0, 0.0], {"ref-a"})
                   for kind in ("raw", "md")]
        self.assertEqual([r[0]["text"] for r in outputs], [source_text, source_text])
        self.assertEqual([r[0]["score"] for r in outputs], [1.0, 1.0])


class RankingTests(unittest.TestCase):
    def test_threshold_includes_equality_and_rejects_below(self):
        records = [row("equal"), row("below"), row("above")]
        scores = [.68, .679, .9]
        vectors = [[score, math.sqrt(1 - score ** 2)] for score in scores]
        hits = rank_hits(records, vectors, [1.0, 0.0], {"ref-a"})
        self.assertEqual([r["id"] for r in hits], ["above", "equal"])
        self.assertEqual(hits[1]["score"], .68)

    def test_multi_source_record_is_rejected_if_any_ref_is_invisible(self):
        records = [row("mixed", refs=["ref-a", "ref-hidden"]), row("visible")]
        diagnostic = {}
        hits = rank_hits(records, [[1., 0.], [1., 0.]], [1., 0.], {"ref-a"},
                         diagnostics=diagnostic)
        self.assertEqual([r["id"] for r in hits], ["visible"])
        self.assertEqual(diagnostic["invalid_ref_ids"], ["mixed"])

    def test_full_records_share_one_budget_and_oversized_text_is_never_cut(self):
        records = [row("a", "甲" * 8001), row("b", "乙" * 7900),
                   row("c", "條件：" + "丙" * 98), row("d", "丁" * 100)]
        diagnostic = {}
        hits = rank_hits(records, [[1., 0.]] * 4, [1., 0.], {"ref-a"},
                         diagnostics=diagnostic)
        self.assertEqual([r["id"] for r in hits], ["b", "d"])
        self.assertEqual([r["text"] for r in hits], [records[1]["text"], records[3]["text"]])
        self.assertEqual(diagnostic["selected_chars"], 8000)
        self.assertEqual(diagnostic["oversized_ids"], ["a"])
        self.assertEqual(diagnostic["budget_skipped_ids"], ["c"])

    def test_same_text_deduplicates_and_top_five_limit_is_shared(self):
        records = [row("a", "duplicate"), row("b", "duplicate")]
        records += [row(str(i)) for i in range(7)]
        hits = rank_hits(records, [[1., 0.]] * len(records), [1., 0.], {"ref-a"})
        self.assertEqual(len(hits), 5)
        self.assertEqual(len({r["text"] for r in hits}), 5)
        # Ensure duplicate records actually enter the selected portion too.
        hits = rank_hits(records[:3], [[1., 0.]] * 3, [1., 0.], {"ref-a"})
        self.assertEqual(len(hits), 2)

    def test_equal_scores_use_id_order_independent_of_input_order(self):
        records = [row("z"), row("a"), row("b")]
        for rows in (records, list(reversed(records))):
            hits = rank_hits(rows, [[1., 0.]] * 3, [1., 0.], {"ref-a"})
            self.assertEqual([r["id"] for r in hits], ["a", "b", "z"])

    def test_results_are_detached_and_zero_limits_select_nothing(self):
        records = [row("a")]
        hits = rank_hits(records, [[1., 0.]], [1., 0.], {"ref-a"})
        hits[0]["source_refs"].clear()
        self.assertEqual(records[0]["source_refs"], ["ref-a"])
        for kwargs in ({"top_k": 0}, {"char_budget": 0}):
            self.assertEqual(rank_hits(records, [[1., 0.]], [1., 0.], {"ref-a"}, **kwargs), [])

    def test_invalid_vectors_fail_instead_of_broadcasting_or_ranking_nan(self):
        cases = [
            ([[1., 0.]], [1.]),
            ([[1., 0., 0.]], [1., 0.]),
            ([[0., 0.]], [1., 0.]),
            ([[float("nan"), 0.]], [1., 0.]),
            ([[float("inf"), 0.]], [1., 0.]),
            ([[1e308, 0.]], [1., 0.]),
            ([[True, 0.]], [1., 0.]),
            ([["1", 0.]], [1., 0.]),
            ([[1., 0.]], [0., 0.]),
            ([[1., 0.]], [float("nan"), 0.]),
            ([], [1., 0.]),
            ([[1., 0.]], []),
        ]
        for vectors, query in cases:
            with self.subTest(vectors=vectors, query=query), self.assertRaises(ValueError):
                rank_hits([row("a")], vectors, query, {"ref-a"})

    def test_invalid_controls_or_duplicate_ids_are_rejected(self):
        for kwargs in ({"top_k": -1}, {"top_k": True}, {"char_budget": 1.5},
                       {"threshold": float("nan")}, {"threshold": 1.1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                rank_hits([row("a")], [[1., 0.]], [1., 0.], {"ref-a"}, **kwargs)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            rank_hits([row("a"), row("a")], [[1., 0.]] * 2, [1., 0.], {"ref-a"})


class FusionTests(unittest.TestCase):
    def test_rrf_uses_rank_not_cosine_and_retains_cosine_separately(self):
        first = [{**row("a"), "score": .99}, {**row("b"), "score": .68}]
        second = [{**row("b"), "score": .71}, {**row("c"), "score": .70}]
        hits = merge_ranks([first, second])
        self.assertEqual([r["id"] for r in hits], ["b", "a", "c"])
        self.assertEqual(hits[0]["rrf_score"], 1 / 62 + 1 / 61)
        self.assertEqual(hits[0]["score"], .68)

    def test_fusion_has_stable_ties_text_dedup_and_one_final_budget(self):
        lists = [[{**row("z", "same"), "score": .9}, {**row("c", "longer"), "score": .8}],
                 [{**row("a", "same"), "score": .9}, {**row("b", "xy"), "score": .8}]]
        diagnostic = {}
        hits = merge_ranks(lists, char_budget=6, diagnostics=diagnostic)
        self.assertEqual([r["id"] for r in hits], ["a", "b"])
        self.assertEqual(diagnostic["selected_chars"], 6)
        self.assertEqual(diagnostic["duplicate_text_ids"], ["z"])
        self.assertEqual(diagnostic["budget_skipped_ids"], ["c"])
        self.assertEqual(len(merge_ranks([[row(str(i)) for i in range(8)]])), 5)

    def test_same_id_cannot_merge_different_text_or_sources(self):
        for other in (row("a", "different"), row("a", refs=["ref-other"])):
            with self.subTest(other=other), self.assertRaises(ValueError):
                merge_ranks([[row("a")], [other]])


if __name__ == "__main__":
    unittest.main()

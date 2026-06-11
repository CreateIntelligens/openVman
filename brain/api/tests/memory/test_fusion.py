"""Tests for memory.fusion — RRF fusion and min-max score normalization."""

from __future__ import annotations

import pytest

from memory.fusion import deduplicate, min_max_normalize, rrf_fuse


# ------------------------------------------------------------------
# rrf_fuse
# ------------------------------------------------------------------


def _rec(text: str, **extra):
    return {"text": text, **extra}


class TestRrfFuse:
    def test_empty_input_returns_empty(self):
        assert rrf_fuse([]) == []
        assert rrf_fuse([[], []]) == []

    def test_single_list_preserves_order(self):
        records = [_rec("a"), _rec("b"), _rec("c")]
        fused = rrf_fuse([records])
        assert [r["text"] for r in fused] == ["a", "b", "c"]

    def test_rrf_score_formula(self):
        # rank 0 in one list of k=60 → 1 / (60 + 1)
        fused = rrf_fuse([[_rec("a")]], k=60)
        assert fused[0]["_rrf_score"] == pytest.approx(1.0 / 61.0)

    def test_record_in_both_lists_accumulates_score(self):
        vector = [_rec("shared"), _rec("v-only")]
        fts = [_rec("f-only"), _rec("shared")]
        fused = rrf_fuse([vector, fts], k=60)
        by_text = {r["text"]: r["_rrf_score"] for r in fused}
        assert by_text["shared"] == pytest.approx(1 / 61 + 1 / 62)
        assert by_text["v-only"] == pytest.approx(1 / 62)
        assert by_text["f-only"] == pytest.approx(1 / 61)
        # shared appears in both lists → ranks first
        assert fused[0]["text"] == "shared"

    def test_merges_fields_from_both_occurrences(self):
        vector = [_rec("shared", _distance=0.3)]
        fts = [_rec("shared", _score=7.5)]
        fused = rrf_fuse([vector, fts])
        assert len(fused) == 1
        assert fused[0]["_distance"] == 0.3
        assert fused[0]["_score"] == 7.5

    def test_first_occurrence_wins_on_conflicting_fields(self):
        vector = [_rec("shared", extra="vector")]
        fts = [_rec("shared", extra="fts")]
        fused = rrf_fuse([vector, fts])
        assert fused[0]["extra"] == "vector"

    def test_does_not_mutate_inputs(self):
        record = _rec("a", _distance=0.1)
        rrf_fuse([[record]])
        assert "_rrf_score" not in record

    def test_custom_key_fn(self):
        a = {"id": 1, "text": "x"}
        b = {"id": 1, "text": "y"}
        fused = rrf_fuse([[a], [b]], key_fn=lambda r: r["id"])
        assert len(fused) == 1


# ------------------------------------------------------------------
# min_max_normalize
# ------------------------------------------------------------------


class TestMinMaxNormalize:
    def test_empty_input(self):
        assert min_max_normalize([], source_field="_distance") == []

    def test_normalizes_to_unit_range(self):
        records = [{"_rrf_score": 0.1}, {"_rrf_score": 0.5}, {"_rrf_score": 0.3}]
        out = min_max_normalize(records, source_field="_rrf_score", out_field="_score")
        scores = [r["_score"] for r in out]
        assert max(scores) == 1.0
        assert min(scores) == 0.0
        assert scores[2] == pytest.approx(0.5)

    def test_invert_for_distance(self):
        records = [{"_distance": 0.2}, {"_distance": 0.8}]
        out = min_max_normalize(records, source_field="_distance", invert=True)
        # smaller distance → higher score
        assert out[0]["_score"] == 1.0
        assert out[1]["_score"] == 0.0

    def test_equal_values_all_get_full_score(self):
        records = [{"_distance": 0.5}, {"_distance": 0.5}]
        out = min_max_normalize(records, source_field="_distance", invert=True)
        assert [r["_score"] for r in out] == [1.0, 1.0]

    def test_records_missing_field_are_passed_through(self):
        records = [{"_distance": 0.1}, {"other": 1}]
        out = min_max_normalize(records, source_field="_distance", invert=True)
        assert "_score" in out[0]
        assert "_score" not in out[1]

    def test_does_not_mutate_inputs(self):
        record = {"_distance": 0.1}
        min_max_normalize([record], source_field="_distance")
        assert "_score" not in record


# ------------------------------------------------------------------
# deduplicate
# ------------------------------------------------------------------


class TestDeduplicate:
    def test_empty_input(self):
        assert deduplicate([]) == []

    def test_exact_duplicate_text_keeps_first(self):
        records = [
            {"text": "same", "_distance": 0.1},
            {"text": "same", "_distance": 0.4},
            {"text": "other"},
        ]
        out = deduplicate(records)
        assert [r["text"] for r in out] == ["same", "other"]
        assert out[0]["_distance"] == 0.1

    def test_near_duplicate_embedding_is_dropped(self):
        records = [
            {"text": "a", "vector": [1.0, 0.0]},
            {"text": "a-paraphrase", "vector": [0.999, 0.01]},  # cos ≈ 1
            {"text": "different", "vector": [0.0, 1.0]},
        ]
        out = deduplicate(records, similarity_threshold=0.95)
        assert [r["text"] for r in out] == ["a", "different"]

    def test_below_threshold_is_kept(self):
        records = [
            {"text": "a", "vector": [1.0, 0.0]},
            {"text": "b", "vector": [0.8, 0.6]},  # cos = 0.8
        ]
        out = deduplicate(records, similarity_threshold=0.95)
        assert len(out) == 2

    def test_records_without_vector_only_exact_dedup(self):
        records = [{"text": "a"}, {"text": "a"}, {"text": "b"}]
        out = deduplicate(records)
        assert [r["text"] for r in out] == ["a", "b"]

    def test_zero_vector_is_not_treated_as_duplicate(self):
        records = [
            {"text": "a", "vector": [0.0, 0.0]},
            {"text": "b", "vector": [0.0, 0.0]},
        ]
        out = deduplicate(records)
        assert len(out) == 2

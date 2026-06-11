"""Tests for memory.retrieval hybrid path — RRF fusion, normalization, dedup."""

from __future__ import annotations

from typing import Any

import pytest

import memory.retrieval as retrieval


# ------------------------------------------------------------------
# Fakes
# ------------------------------------------------------------------


class _FakeSearchResult:
    def __init__(self, records: list[dict[str, Any]]):
        self._records = records

    def limit(self, n: int) -> "_FakeSearchResult":
        return _FakeSearchResult(self._records[:n])

    def to_list(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._records]


class _FakeTable:
    """search(vector) → vector results; search(text, query_type='fts') → FTS results.

    fts_records 可以是 list(所有文字查詢共用)或 dict(依查詢文字分流,
    用於 query expansion 測試)。vector_records 同理,dict 以 tuple(vector) 為鍵。
    """

    def __init__(self, vector_records, fts_records=None, fts_raises=False):
        self.vector_records = vector_records
        self.fts_records = fts_records or []
        self.fts_raises = fts_raises

    def search(self, query, query_type: str = "vector"):
        if query_type == "fts":
            if self.fts_raises:
                raise RuntimeError("fts index missing")
            if isinstance(self.fts_records, dict):
                return _FakeSearchResult(self.fts_records.get(query, []))
            return _FakeSearchResult(self.fts_records)
        if isinstance(self.vector_records, dict):
            return _FakeSearchResult(self.vector_records.get(tuple(query), []))
        return _FakeSearchResult(self.vector_records)


class _FakeConfig:
    rag_distance_cutoff = 0.85
    rag_rrf_k = 60
    rag_dedup_similarity_threshold = 0.95


def _rec(text: str, distance: float | None = None, vector=None, **extra):
    record = {"text": text, "metadata": "{}", **extra}
    if distance is not None:
        record["_distance"] = distance
    if vector is not None:
        record["vector"] = vector
    return record


@pytest.fixture()
def patched(monkeypatch: pytest.MonkeyPatch):
    """Patch config and table plumbing; returns a setter for the fake table."""
    import config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _FakeConfig())
    monkeypatch.setattr(retrieval, "vector_table_exists", lambda *a, **k: True)
    monkeypatch.setattr(retrieval, "list_disabled_document_paths", lambda *a, **k: set())
    monkeypatch.setattr(retrieval, "record_trace", lambda **k: None)

    def use_table(table):
        monkeypatch.setattr(retrieval, "get_search_table", lambda *a, **k: table)

    return use_table


def _search(query_text="hello", query_type="hybrid", top_k=5, expansion_terms=None):
    return retrieval.search_records(
        "knowledge",
        query_vector=[0.1, 0.2],
        top_k=top_k,
        query_text=query_text,
        query_type=query_type,
        expansion_terms=expansion_terms,
    )


# ------------------------------------------------------------------
# Hybrid RRF fusion
# ------------------------------------------------------------------


class TestHybridRrf:
    def test_record_in_both_lists_ranks_first(self, patched):
        patched(_FakeTable(
            vector_records=[_rec("v-only", 0.2), _rec("shared", 0.3)],
            fts_records=[_rec("shared"), _rec("f-only")],
        ))
        results = _search()
        assert results[0]["text"] == "shared"

    def test_scores_are_normalized(self, patched):
        patched(_FakeTable(
            vector_records=[_rec("v-only", 0.2), _rec("shared", 0.3)],
            fts_records=[_rec("shared"), _rec("f-only")],
        ))
        results = _search()
        scores = [r["_score"] for r in results]
        assert scores[0] == 1.0
        assert all(0.0 <= s <= 1.0 for s in scores)
        assert scores == sorted(scores, reverse=True)

    def test_fts_failure_falls_back_to_vector_with_score(self, patched):
        patched(_FakeTable(
            vector_records=[_rec("near", 0.1), _rec("far", 0.5)],
            fts_raises=True,
        ))
        results = _search()
        assert [r["text"] for r in results] == ["near", "far"]
        assert results[0]["_score"] == 1.0
        assert results[1]["_score"] == 0.0

    def test_fts_only_hit_survives_distance_cutoff(self, patched):
        patched(_FakeTable(
            vector_records=[_rec("v", 0.2)],
            fts_records=[_rec("keyword-hit")],
        ))
        results = _search()
        assert "keyword-hit" in [r["text"] for r in results]

    def test_vector_hit_over_cutoff_is_dropped(self, patched):
        patched(_FakeTable(
            vector_records=[_rec("good", 0.2), _rec("too-far", 0.99)],
            fts_records=[],
        ))
        results = _search()
        assert [r["text"] for r in results] == ["good"]


# ------------------------------------------------------------------
# Dedup in search_records
# ------------------------------------------------------------------


class TestSearchDedup:
    def test_exact_duplicate_text_removed(self, patched):
        patched(_FakeTable(
            vector_records=[_rec("dup", 0.1), _rec("dup", 0.2), _rec("uniq", 0.3)],
            fts_records=[],
        ))
        results = _search()
        assert [r["text"] for r in results] == ["dup", "uniq"]

    def test_near_duplicate_embedding_removed(self, patched):
        patched(_FakeTable(
            vector_records=[
                _rec("a", 0.1, vector=[1.0, 0.0]),
                _rec("a-paraphrase", 0.2, vector=[0.999, 0.01]),
                _rec("different", 0.3, vector=[0.0, 1.0]),
            ],
            fts_records=[],
        ))
        results = _search()
        assert [r["text"] for r in results] == ["a", "different"]
        # vector 欄位最終仍會被剝除
        assert all("vector" not in r for r in results)


# ------------------------------------------------------------------
# Query expansion (multi-query RRF)
# ------------------------------------------------------------------


class TestQueryExpansion:
    def test_expansion_term_results_are_fused(self, patched, monkeypatch):
        # 原文 vector 查到 base;擴展詞「退款流程」FTS 查到 expanded-hit
        monkeypatch.setattr(retrieval, "encode_text", lambda text, version=None: [0.9, 0.9])
        patched(_FakeTable(
            vector_records={(0.1, 0.2): [_rec("base", 0.2)], (0.9, 0.9): []},
            fts_records={"hello": [], "退款流程": [_rec("expanded-hit")]},
        ))
        results = _search(expansion_terms=["退款流程"])
        assert {r["text"] for r in results} == {"base", "expanded-hit"}

    def test_hit_across_original_and_expansion_ranks_first(self, patched, monkeypatch):
        monkeypatch.setattr(retrieval, "encode_text", lambda text, version=None: [0.9, 0.9])
        patched(_FakeTable(
            vector_records={
                (0.1, 0.2): [_rec("only-original", 0.1), _rec("both", 0.2)],
                (0.9, 0.9): [_rec("both", 0.3)],
            },
            fts_records={},
        ))
        results = _search(expansion_terms=["改寫詞"])
        assert results[0]["text"] == "both"

    def test_encode_failure_skips_term(self, patched, monkeypatch):
        def boom(text, version=None):
            raise RuntimeError("embedder down")

        monkeypatch.setattr(retrieval, "encode_text", boom)
        patched(_FakeTable(
            vector_records={(0.1, 0.2): [_rec("base", 0.2)]},
            fts_records={},
        ))
        results = _search(expansion_terms=["退款流程"])
        assert [r["text"] for r in results] == ["base"]

    def test_no_expansion_terms_keeps_existing_behavior(self, patched):
        patched(_FakeTable(
            vector_records=[_rec("near", 0.1), _rec("far", 0.5)],
            fts_records=[],
        ))
        results = _search(expansion_terms=[])
        assert [r["text"] for r in results] == ["near", "far"]

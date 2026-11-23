"""Query embedding down → search_knowledge still answers from the full-text index."""

from __future__ import annotations

from typing import Any

import httpx
import pytest


class _FtsOnlyTable:
    """Answers full-text queries; any vector search fails the test."""

    def __init__(self, rows):
        self.rows = rows

    def search(self, query, query_type=None):
        assert query_type == "fts", "vector search must not run without a query vector"
        hits = [dict(r, _score=1.0) for r in self.rows if query in r["text"].split()]
        return type("Q", (), {"limit": lambda _s, n: type("R", (), {"to_list": lambda _r: hits[:n]})()})()


def test_search_without_query_vector_uses_full_text_only():
    from memory import retrieval

    table = _FtsOnlyTable([
        {"text": "DIVA 系列 重型泥漿泵", "path": "diva.md", "vector": [1.0, 0.0]},
        {"text": "EUS 加裝 底盤", "path": "eus.md", "vector": [0.0, 1.0]},
    ])
    window: dict[str, Any] = {}
    records = retrieval._safe_search(
        table, None, query_text="DIVA", limit=5, rrf_k=60,
        expansion_terms=["泥漿"], embedding_version=None, window=window,
    )

    assert [r["path"] for r in records] == ["diva.md"]
    assert records[0]["_fts_match"] is True and records[0]["_score"] == pytest.approx(1.0)
    assert retrieval._passes_relevance_cutoff(records[0], cutoff=0.1, fts_cutoff=0.2)
    assert retrieval._window_settled(window, cutoff=0.5, fts_cutoff=1.0)


def test_embedding_timeout_falls_back_to_lexical_for_every_query(monkeypatch):
    import memory.embedder as embedder
    import memory.retrieval as retrieval
    from tools.builtin import knowledge_tools
    from tools.context import active_project_id, active_user_message

    encode_calls: list[str] = []

    def encode(query, **_kw):
        encode_calls.append(query)
        try:
            raise httpx.ReadTimeout("")
        except httpx.ReadTimeout as cause:
            raise RuntimeError("沒有可用的 embedding version 可供查詢") from cause

    searches: list[tuple[str, Any]] = []

    def search_records(*, query_text, query_vector, **_kw):
        searches.append((query_text, query_vector))
        return [{"text": f"{query_text} 的答案", "path": f"{query_text}.md"}]

    attempts: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(embedder, "encode_query_with_fallback", encode)
    monkeypatch.setattr(retrieval, "search_records", search_records)
    monkeypatch.setattr(knowledge_tools, "_expand_via_graph", lambda *a, **kw: [])
    monkeypatch.setattr(knowledge_tools, "primary_language", lambda project_id: "zh-TW")
    monkeypatch.setattr(
        knowledge_tools, "record_node_attempt", lambda node, **kw: attempts.append((node, kw)),
    )
    project_token = active_project_id.set("p")
    message_token = active_user_message.set("")
    try:
        result = knowledge_tools._search_tool("knowledge", {"queries": ["DIVA", "EUS"]})
    finally:
        active_project_id.reset(project_token)
        active_user_message.reset(message_token)

    # 第一條等過 embedding 一次就知道它壞了，第二條不再等。
    assert encode_calls == ["DIVA"]
    assert searches == [("DIVA", None), ("EUS", None)]
    assert {r["path"] for r in result["results"]} == {"DIVA.md", "EUS.md"}
    fallback = [kw for node, kw in attempts if node == "rag_lexical_fallback"]
    assert len(fallback) == 1 and fallback[0]["outcome"] == "timeout"
    assert [kw["outcome"] for node, kw in attempts if node == "rag_query"] == ["ok", "ok"]


def test_lancedb_errors_are_not_mistaken_for_an_embedding_outage(monkeypatch):
    import memory.embedder as embedder
    import memory.retrieval as retrieval
    from tools.builtin import knowledge_tools

    monkeypatch.setattr(
        embedder, "encode_query_with_fallback",
        lambda query, **_kw: type("Route", (), {"vector": [1.0], "version": "gemma"})(),
    )

    def broken(**_kw):
        raise OSError("lance file missing")

    monkeypatch.setattr(retrieval, "search_records", broken)
    with pytest.raises(OSError):
        knowledge_tools._search_one_with_fallback(
            "knowledge", "DIVA", 3, "default", "p", None, lexical_only=False,
        )

"""The /chat response says whether the knowledge base answered the turn.

整合方用 ``no_answer`` 決定要不要把回答換成固定的拒答句，所以只看 search_knowledge
的引用：網路、記憶的引用不算知識庫命中。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core import chat_service


def _search(name: str, *uris: str) -> dict:
    citations = [{"uri": uri, "title": uri, "distance": 0.2} for uri in uris]
    return {"name": name, "result": json.dumps({"ok": True, "data": {"citations": citations}})}


@pytest.fixture(autouse=True)
def _doc_meta(monkeypatch):
    meta = {
        "knowledge/qa/faq.md": {"source_type": "qa"},
        "knowledge/manual.md": {"source_type": "upload"},
    }
    monkeypatch.setattr("knowledge.doc_meta.load_doc_meta", lambda project_id: meta)


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        (
            [_search("search_knowledge", "knowledge/manual.md", "knowledge/qa/faq.md")],
            {"answer_source": "qa", "knowledge_searched": True, "no_answer": False},
        ),
        (
            [_search("search_knowledge", "knowledge/manual.md")],
            {"answer_source": "knowledge", "knowledge_searched": True, "no_answer": False},
        ),
        (
            [],
            {"answer_source": "none", "knowledge_searched": False, "no_answer": False},
        ),
        (
            [_search("search_knowledge")],
            {"answer_source": "none", "knowledge_searched": True, "no_answer": True},
        ),
        (
            [_search("search_knowledge"), _search("search_web", "https://example.com")],
            {"answer_source": "none", "knowledge_searched": True, "no_answer": True},
        ),
        (
            [{"name": "search_knowledge", "result": json.dumps({"ok": False, "error": "x"})}],
            {"answer_source": "none", "knowledge_searched": True, "no_answer": True},
        ),
        (
            [_search("search_memory", "memories/2026-10-01.md")],
            {"answer_source": "none", "knowledge_searched": False, "no_answer": False},
        ),
    ],
    ids=["qa", "knowledge", "not-searched", "searched-empty", "web-only", "search-error", "memory-only"],
)
def test_answer_source_fields(steps, expected):
    assert chat_service.answer_source_fields(steps, "pr") == expected


def test_finalize_returns_the_fields(monkeypatch):
    monkeypatch.setattr(chat_service, "_pii_writeback_executor", SimpleNamespace(submit=lambda *a, **k: None))
    context = SimpleNamespace(
        request_context={"metadata": {}}, trace_id="t", user_message="問題",
        turn_decision=None, session_id="s", persona_id="p", project_id="pr", prior_messages=[],
    )
    response = chat_service.finalize_generation(
        context, "回答", [_search("search_knowledge", "knowledge/qa/faq.md")], persist=False,
    )
    assert response["answer_source"] == "qa"
    assert response["knowledge_searched"] is True
    assert response["no_answer"] is False

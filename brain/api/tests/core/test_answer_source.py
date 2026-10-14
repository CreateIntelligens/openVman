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


def _judge(monkeypatch, probability=None, error=None):
    calls = []
    monkeypatch.setenv("NO_ANSWER_JUDGE_ENABLED", "true")
    monkeypatch.setattr("config._settings", None)

    def fake_decide_noul(state, question, *, timeout, purpose):
        calls.append({"state": state, "purpose": purpose, "timeout": timeout})
        if error:
            raise error
        return probability

    monkeypatch.setattr("core.decision_router.decide_noul", fake_decide_noul)
    return calls


def test_reply_saying_not_found_marks_no_answer_even_with_citations(monkeypatch):
    # 2026-10-14 正式機：問「火星上有幾座醫院？」檢索到院內服務 QA，回答說資料沒有提到，
    # 原本 no_answer 卻是 false（檢索門檻刻意放寬，沾邊的段落也會帶回）。
    calls = _judge(monkeypatch, probability=0.99)
    fields = chat_service.answer_source_fields(
        [_search("search_knowledge", "knowledge/qa/faq.md")], "pr",
        question="火星上有幾座醫院？", reply="資料中沒有提到火星上有幾座醫院。",
    )
    assert fields == {"answer_source": "qa", "knowledge_searched": True, "no_answer": True}
    assert calls[0]["purpose"] == "no_answer"
    assert calls[0]["state"]["assistant_reply"].startswith("資料中沒有提到")


def test_real_answer_stays_answered(monkeypatch):
    _judge(monkeypatch, probability=0.04)
    fields = chat_service.answer_source_fields(
        [_search("search_knowledge", "knowledge/manual.md")], "pr",
        question="最大流量？", reply="最大流量是 330 LPM。",
    )
    assert fields["no_answer"] is False


def test_judge_failure_falls_back_to_citations(monkeypatch):
    _judge(monkeypatch, error=RuntimeError("all decision providers failed"))
    fields = chat_service.answer_source_fields(
        [_search("search_knowledge", "knowledge/manual.md")], "pr",
        question="q", reply="資料中沒有提到。",
    )
    assert fields["no_answer"] is False


def test_judge_is_skipped_when_nothing_was_cited(monkeypatch):
    # 沒引用已經確定是 no_answer；沒查知識庫（打招呼）也不需要多問一次。
    calls = _judge(monkeypatch, probability=0.99)
    chat_service.answer_source_fields([_search("search_knowledge")], "pr", question="q", reply="r")
    chat_service.answer_source_fields([], "pr", question="你好", reply="你好")
    assert calls == []


def test_judge_can_be_turned_off(monkeypatch):
    calls = _judge(monkeypatch, probability=0.99)
    settings = chat_service.get_settings()
    monkeypatch.setattr(
        chat_service, "get_settings",
        lambda: SimpleNamespace(**{**settings.__dict__, "no_answer_judge_enabled": False}),
    )
    fields = chat_service.answer_source_fields(
        [_search("search_knowledge", "knowledge/manual.md")], "pr", question="q", reply="查不到",
    )
    assert fields["no_answer"] is False and calls == []

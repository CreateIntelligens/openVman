"""ChatRequest.language locks the reply and retrieval language for the whole turn.

跟 preferred_language（只是提示）不同：指定後回覆、檢索都只用這個語言，不看使用者
這句話、不看決策結果，決策關閉或失敗時也一樣。
"""

from __future__ import annotations

import collections
import importlib
import types

import pytest
from pydantic import ValidationError

from core import prompt_templates, turn_decisions
from core.decision_router import DecisionResult
from core.pipeline import RouteDecision
from core.turn_decisions import (
    TurnDecisionConfig,
    TurnPolicy,
    build_turn_evidence,
    run_turn_decision,
)
from protocol.schemas import ChatRequest


@pytest.fixture(autouse=True)
def _project(monkeypatch):
    monkeypatch.setattr(prompt_templates, "_primary_language", lambda project_id: "zh")
    monkeypatch.setattr(prompt_templates, "_reply_seconds", lambda project_id: 20)


def _decide(**overrides):
    return run_turn_decision(
        user_text="請問掛號時間是什麼時候？", history=[], project_id="p",
        project_language="zh", speech_language="", available_tools=(),
        turn_id="t", **{"config": TurnDecisionConfig(), **overrides},
    )


def _asked_for_spanish(monkeypatch):
    answers = {
        "requested_response_language": {
            "type": "choice", "choice": "es", "confidence": 0.95,
            "probabilities": {"es": 0.95, "other": 0.05},
        },
    }
    monkeypatch.setattr(
        turn_decisions, "decide",
        lambda *a, **kw: DecisionResult(answers, "clef", "clef-primary", "clef-flash"),
    )


def test_request_accepts_only_lockable_languages():
    assert ChatRequest(message="hi").language is None
    for code in ("zh", "en", "es", "ja", "ko"):
        assert ChatRequest(message="hi", language=code).language == code
    for code in ("nan", "fr", "other"):
        with pytest.raises(ValidationError, match="language 只能是"):
            ChatRequest(message="hi", language=code)


def test_locked_language_overrides_a_chinese_message_and_the_decision(monkeypatch):
    _asked_for_spanish(monkeypatch)
    decision = _decide(locked_language="en")
    assert decision.source == "clef"
    assert decision.policy.response_language == "en"
    assert decision.policy.retrieval_language == "en"


def test_locked_language_holds_when_decisions_are_disabled_or_failing(monkeypatch):
    disabled = _decide(config=TurnDecisionConfig(enabled=False), locked_language="es")
    assert (disabled.policy.response_language, disabled.policy.retrieval_language) == ("es", "es")

    def broken(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(turn_decisions, "decide", broken)
    failed = _decide(locked_language="ja")
    assert failed.dependency_unavailable
    assert (failed.policy.response_language, failed.policy.retrieval_language) == ("ja", "ja")


def test_without_a_lock_the_decision_still_decides(monkeypatch):
    _asked_for_spanish(monkeypatch)
    decision = _decide(preferred_language="en")
    assert decision.policy.response_language == "es"
    assert decision.policy.retrieval_language == "zh"


def test_preferred_language_alone_still_follows_a_clear_message():
    reply = prompt_templates.reply_language_line(
        "p", "請問你們今天幾點開始看診？我想知道詳細的掛號時間。", preferred_language="en",
    )
    assert "繁體中文" in reply and "一律" not in reply
    decision = _decide(config=TurnDecisionConfig(enabled=False), preferred_language="en")
    assert decision.policy.response_language is None
    assert decision.policy.retrieval_language == "zh"


def test_the_decision_evidence_records_the_lock_only_when_present():
    locked = build_turn_evidence(
        "ok", [], speech_language="", project_language="zh", available_tools=(),
        locked_language="en",
    )
    plain = build_turn_evidence(
        "ok", [], speech_language="", project_language="zh", available_tools=(),
    )
    assert locked["locked_language"] == "en"
    assert "locked_language" not in plain


def test_prompt_pins_the_language_even_for_other_languages_and_without_a_policy():
    line = prompt_templates.reply_language_line(
        "p", "請用中文回答我", resolved_language="zh", preferred_language="zh",
        locked_language="en",
    )
    assert "一律用English回答，即使使用者用其他語言" in line
    assert "不超過 30 個單字" in line  # 長度規則也照鎖定語言算（20 秒 × 1.5）


def test_system_prompt_pins_the_language_with_no_turn_policy(monkeypatch):
    from core import prompt_builder

    monkeypatch.setattr(
        prompt_builder, "load_core_workspace_context",
        lambda *a, **k: collections.defaultdict(str),
    )
    for code, name in (("es", "Español"), ("ja", "日本語")):
        system = prompt_builder.build_chat_messages(
            "請用中文回答", {"project_id": "default"}, [], turn_policy=None,
            locked_language=code,
        )[0]["content"]
        assert f"一律用{name}回答，即使使用者用其他語言" in system
    unlocked = prompt_builder.build_chat_messages(
        "請用中文回答", {"project_id": "default"}, [],
    )[0]["content"]
    assert "一律用" not in unlocked.split("這一輪的回答語言")[-1]


def test_execute_generation_sets_a_strict_retrieval_language_and_resets_it(monkeypatch):
    from core import chat_service
    from tools.context import active_retrieval_language, active_retrieval_language_strict

    seen: list[tuple[str, bool]] = []

    def fake_loop(*args, **kwargs):
        seen.append((active_retrieval_language.get(), active_retrieval_language_strict.get()))
        return chat_service.AgentLoopResult(reply="ok", tool_steps=[])

    monkeypatch.setattr(chat_service, "run_agent_loop", fake_loop)

    def context(lock, decision=None):
        return chat_service.GenerationContext(
            trace_id="t", persona_id="p", project_id="pr", session_id="s",
            route=RouteDecision("rag", False, False), user_message="你好",
            request_context={"metadata": {}}, prompt_messages=[],
            turn_decision=decision, preferred_language="nan", locked_language=lock,
        )

    decided = types.SimpleNamespace(
        policy=TurnPolicy(retrieval_language="zh"), dependency_unavailable=False,
    )
    chat_service.execute_generation(context("en"))
    chat_service.execute_generation(context("es", decided))
    chat_service.execute_generation(context(None, decided))
    chat_service.execute_generation(context(None))
    # 沒鎖時照舊：有決策用決策、只有提示用提示，嚴格旗標一律關。
    assert seen == [("en", True), ("es", True), ("zh", False), ("nan", False)]
    assert (active_retrieval_language.get(), active_retrieval_language_strict.get()) == ("", False)


def test_search_tool_asks_for_strict_filtering_only_when_locked(monkeypatch):
    from tools.builtin import knowledge_tools
    from tools.context import (
        active_project_id,
        active_retrieval_language,
        active_retrieval_language_strict,
        active_user_message,
    )

    embedder = importlib.import_module("memory.embedder")
    retrieval = importlib.import_module("memory.retrieval")
    seen: list[tuple[str | None, bool]] = []
    monkeypatch.setattr(
        embedder, "encode_query_with_fallback",
        lambda *a, **kw: types.SimpleNamespace(vector=[0.1], version="gemma"),
    )
    monkeypatch.setattr(
        retrieval, "search_records",
        lambda *a, **kw: seen.append((kw.get("language"), kw.get("strict_language", False))) or [],
    )
    monkeypatch.setattr(knowledge_tools, "_expand_via_graph", lambda merged, *a, **kw: [])

    def run(strict):
        tokens = [
            (active_user_message, active_user_message.set("掛號時間")),
            (active_project_id, active_project_id.set("proj-x")),
            (active_retrieval_language, active_retrieval_language.set("en")),
            (active_retrieval_language_strict, active_retrieval_language_strict.set(strict)),
        ]
        try:
            knowledge_tools._search_tool("knowledge", {"queries": ["opening hours"]})
        finally:
            for var, token in reversed(tokens):
                var.reset(token)

    run(True)
    run(False)
    assert seen and {s for s in seen[: len(seen) // 2]} == {("en", True)}
    assert {s for s in seen[len(seen) // 2:]} == {("en", False)}


def test_strict_graph_neighbours_keep_only_the_locked_language(monkeypatch):
    from tools.builtin import knowledge_tools

    monkeypatch.setattr(
        "memory.retrieval.resolve_document_languages",
        lambda paths, project_id: {"a.md": "en", "b.md": "zh"},
    )
    related = [
        {"metadata": '{"path": "a.md"}'},
        {"metadata": '{"path": "b.md"}'},
        {"metadata": '{"path": "b.md", "language": "en"}'},
    ]
    kept = knowledge_tools._only_language(related, "en", "p")
    assert kept == [related[0], related[2]]

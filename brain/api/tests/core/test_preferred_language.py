"""The caller's language hint fills in only where the message shows no language.

整合方讓使用者一開始選語言（台語／華語／英文），但那只是參考：使用者這句話看得出
語言、或明講要哪種語言時照使用者；短句、型號這類看不出語言的才用選的語言。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core import prompt_templates
from core.pipeline import RouteDecision
from core.turn_decisions import (
    TurnDecision,
    TurnDecisionConfig,
    TurnPolicy,
    build_turn_evidence,
    resolve_retrieval_language,
    run_turn_decision,
)
from protocol.schemas import ChatRequest


@pytest.fixture(autouse=True)
def _project(monkeypatch):
    monkeypatch.setattr(prompt_templates, "_primary_language", lambda project_id: "zh")
    monkeypatch.setattr(prompt_templates, "_reply_seconds", lambda project_id: 20)


def test_hint_answers_short_input_that_shows_no_language():
    line = prompt_templates.reply_language_line("p", "ok", preferred_language="en")
    assert line.startswith("這一輪的回答語言：English。")


def test_hint_names_the_fallback_for_unclear_input():
    line = prompt_templates.reply_language_line("p", "EUBL pump specs", preferred_language="en")
    assert "只有型號、數字這類看不出語言的輸入才用English。" in line


def test_clear_message_language_still_wins_over_the_hint():
    line = prompt_templates.reply_language_line(
        "p", "What is the max flow of the HIPPO series?", preferred_language="zh",
    )
    assert line.startswith("這一輪的回答語言：English。")
    chinese = prompt_templates.reply_language_line(
        "p", "HIPPO 系列最大流量是多少？", preferred_language="en",
    )
    assert chinese.startswith("這一輪的回答語言：繁體中文。")


def test_explicit_language_request_still_wins_over_the_hint():
    line = prompt_templates.reply_language_line(
        "p", "ok", resolved_language="es", preferred_language="en",
    )
    assert line.startswith("這一輪的回答語言：Español。")


def test_taiwanese_hint_replies_in_traditional_chinese():
    assert prompt_templates.reply_language_line(
        "p", "我想欲問掛號", preferred_language="nan",
    ).startswith("這一輪的回答語言：繁體中文。")
    assert prompt_templates.reply_language_line(
        "p", "ok", preferred_language="nan",
    ).startswith("這一輪的回答語言：繁體中文。")


def test_without_hint_the_reply_line_is_unchanged():
    for message in ("ok", "EUBL pump specs", "What is the max flow?", "流量多少？"):
        assert prompt_templates.reply_language_line(
            "p", message, preferred_language="",
        ) == prompt_templates.reply_language_line("p", message)


@pytest.mark.parametrize(
    ("message", "hint", "expected"),
    [
        ("我想欲問掛號", "nan", "nan"),
        ("ok", "nan", "nan"),
        ("What time does the clinic open?", "nan", "en"),
        ("ok", "en", "en"),
        ("What time does the clinic open?", "zh", "en"),
        ("掛號時間？", "", "zh"),
        ("ok", "", "zh"),
    ],
)
def test_retrieval_language_uses_the_hint_only_as_fallback(message, hint, expected):
    assert resolve_retrieval_language(
        user_text=message, project_language="zh", speech_language="",
        preferred_language=hint,
    ) == expected


def test_turn_decision_baseline_prefers_taiwanese_documents_for_the_nan_hint():
    decision = run_turn_decision(
        user_text="我想欲問掛號", history=[], project_id="p", project_language="zh",
        speech_language="", available_tools=(), config=TurnDecisionConfig(enabled=False),
        turn_id="t", preferred_language="nan",
    )
    assert decision.policy.retrieval_language == "nan"
    assert decision.policy.response_language is None


def test_hint_is_given_to_the_decision_model_only_when_present():
    with_hint = build_turn_evidence(
        "ok", [], speech_language="", project_language="zh",
        available_tools=(), preferred_language="en",
    )
    without = build_turn_evidence(
        "ok", [], speech_language="", project_language="zh", available_tools=(),
    )
    assert with_hint["user_preferred_language"] == "en"
    assert "user_preferred_language" not in without


def test_invalid_hint_is_rejected_and_absent_hint_is_none():
    with pytest.raises(ValidationError):
        ChatRequest(message="hi", preferred_language="de")
    assert ChatRequest(message="hi").preferred_language is None
    assert ChatRequest(message="hi", preferred_language="nan").preferred_language == "nan"


def test_search_uses_the_hint_when_no_turn_decision_ran(monkeypatch):
    from core import chat_service
    from tools.context import active_retrieval_language

    seen: list[str] = []

    def fake_loop(*args, **kwargs):
        seen.append(active_retrieval_language.get())
        return chat_service.AgentLoopResult(reply="好", tool_steps=[])

    monkeypatch.setattr(chat_service, "run_agent_loop", fake_loop)
    monkeypatch.setattr("knowledge.kb_settings.primary_language", lambda project_id: "zh")

    def context(hint, decision=None):
        return chat_service.GenerationContext(
            trace_id="t", persona_id="p", project_id="pr", session_id="s",
            route=RouteDecision("rag", False, False), user_message="我想欲問掛號",
            request_context={"metadata": {}}, prompt_messages=[],
            turn_decision=decision, preferred_language=hint,
        )

    chat_service.execute_generation(context("nan"))
    chat_service.execute_generation(context(None))
    decided = TurnDecision(turn_id="t", policy=TurnPolicy(retrieval_language="nan"), source="baseline")
    chat_service.execute_generation(context("nan", decided))
    assert seen == ["nan", "", "nan"]


def test_chat_route_forwards_the_hint_to_generation(monkeypatch):
    from types import SimpleNamespace

    from routes import chat as chat_routes

    calls: list[dict] = []
    monkeypatch.setattr(chat_routes, "_maybe_rewrite_slash", lambda payload: payload.model_dump())
    monkeypatch.setattr(chat_routes, "build_message_envelope", lambda *args, **kwargs: "envelope")
    monkeypatch.setattr(
        chat_routes, "prepare_generation",
        lambda envelope, **kwargs: calls.append(kwargs) or "context",
    )
    request = SimpleNamespace(headers={})
    chat_routes._prepare_chat_context(request, ChatRequest(message="ok", preferred_language="en"))
    chat_routes._prepare_chat_context(request, ChatRequest(message="ok"))
    assert [call["preferred_language"] for call in calls] == ["en", None]

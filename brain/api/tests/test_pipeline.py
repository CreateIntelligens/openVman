"""Tests for core.pipeline — route, guard session limits, context budget."""

from __future__ import annotations

import importlib
import sys
import types
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from core.pipeline import RouteDecision, enforce_context_budget, route_message
from core.prompt_builder import build_chat_messages
from protocol.message_envelope import BrainMessage, MessageEnvelope, RequestContext, METADATA_ORIGINAL_USER_MESSAGE
from safety import guardrails


# --- helpers ---


def _make_brain_message(
    *,
    role: str = "user",
    content: str = "你好",
    metadata: dict[str, str] | None = None,
) -> BrainMessage:
    return BrainMessage(
        role=role,
        content=content,
        trace_id="trace_test",
        session_id="sess_test",
        persona_id="default",
        project_id="default",
        locale="zh-TW",
        channel="web",
        metadata={} if metadata is None else metadata,
    )


def _make_request_context(
    *,
    message_type: str = "user",
    session_id: str | None = "sess_test",
) -> RequestContext:
    return RequestContext(
        trace_id="trace_test",
        session_id=session_id,
        message_type=message_type,
        channel="web",
        locale="zh-TW",
        persona_id="default",
        project_id="default",
        client_ip="127.0.0.1",
        metadata={},
    )


def _make_envelope(
    *,
    content: str = "你好",
    message_type: str = "user",
    session_id: str | None = "sess_test",
) -> MessageEnvelope:
    return MessageEnvelope(
        content=content,
        context=_make_request_context(message_type=message_type, session_id=session_id),
    )


def _load_chat_service(monkeypatch: pytest.MonkeyPatch):
    from conftest import make_fake_agent_loop, stub_chat_service_deps

    stub_chat_service_deps(monkeypatch)
    monkeypatch.setitem(sys.modules, "core.agent_loop", make_fake_agent_loop())
    sys.modules.pop("core.chat_service", None)
    return importlib.import_module("core.chat_service")


_BASE_PROMPT_SETTINGS = {
    "prompt_identity_char_budget": 0,
    "prompt_soul_char_budget": 0,
    "prompt_memory_char_budget": 0,
    "prompt_agents_char_budget": 0,
    "prompt_tools_char_budget": 0,
    "prompt_learnings_char_budget": 0,
    "prompt_errors_char_budget": 0,
    "prompt_context_char_budget": 0,
    "prompt_system_char_budget": 500,
    "prompt_total_char_budget": 500,
}
_EMPTY_WORKSPACE_CONTEXT = {
    "identity": "",
    "soul": "",
    "memory": "",
    "agents": "",
    "tools": "",
    "learnings": "",
    "errors": "",
}


def _stub_prompt_builder(
    monkeypatch: pytest.MonkeyPatch,
    *,
    settings_overrides: dict[str, int] | None = None,
    workspace_overrides: dict[str, str] | None = None,
    summary: str = "",
    recent_messages: list[dict[str, str]] | None = None,
) -> None:
    settings = {**_BASE_PROMPT_SETTINGS, **(settings_overrides or {})}
    workspace = {**_EMPTY_WORKSPACE_CONTEXT, **(workspace_overrides or {})}
    selected_messages = [] if recent_messages is None else recent_messages

    monkeypatch.setattr("core.prompt_builder.get_settings", lambda: SimpleNamespace(**settings))
    monkeypatch.setattr(
        "core.prompt_builder.load_core_workspace_context",
        lambda persona_id, project_id="default": workspace,
    )
    monkeypatch.setattr("core.prompt_builder.summarize_message_history", lambda session_messages: summary)
    monkeypatch.setattr("core.prompt_builder.select_recent_messages", lambda session_messages: selected_messages)


# --- route tests ---


@pytest.mark.parametrize(
    ("role", "content", "expected_path", "expected_skip_rag", "expected_skip_tools"),
    [
        ("user", "你好", "direct", True, True),
        ("user", "謝謝你", "direct", True, True),
        ("user", "請幫我查一下知識庫裡的退款規則", "tool", False, False),
        ("user", "幫我看看 docs 裡的部署說明", "tool", False, False),
        ("user", "請記住我是男生", "tool", False, False),
        ("user", "請幫我重建圖譜", "tool", False, False),
        ("system", "ignored", "direct", True, True),
        ("assistant", "ignored", "direct", True, True),
        ("control", "ignored", "direct", True, True),
        ("tool", "ignored", "tool", True, False),
    ],
)
def test_route_message(
    role: str,
    content: str,
    expected_path: str,
    expected_skip_rag: bool,
    expected_skip_tools: bool,
) -> None:
    decision = route_message(_make_brain_message(role=role, content=content))

    assert decision.path == expected_path
    assert decision.skip_rag is expected_skip_rag
    assert decision.skip_tools is expected_skip_tools


def test_route_message_forces_tool_path_for_rewritten_slash_command() -> None:
    decision = route_message(
        _make_brain_message(
            content="[系統指令] 請立即呼叫工具 `joke:get_joke`，不需要額外參數。",
            metadata={METADATA_ORIGINAL_USER_MESSAGE: "/joke"},
        )
    )

    assert decision.path == "tool"
    assert decision.skip_rag is False
    assert decision.skip_tools is False


# --- enforce_context_budget tests ---


def test_enforce_context_budget_noop_when_within_budget() -> None:
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "hi"},
    ]
    result = enforce_context_budget(messages, total_char_budget=10000)

    assert result == messages


def test_enforce_context_budget_trims_history_first() -> None:
    messages = [
        {"role": "system", "content": "S" * 100},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "older question"},
        {"role": "assistant", "content": "older answer"},
        {"role": "user", "content": "current"},
    ]
    # budget is tight: system(100) + current user(7) = 107, but total is much more
    result = enforce_context_budget(messages, total_char_budget=150)

    # system and last user must survive
    assert result[0]["role"] == "system"
    assert result[-1]["role"] == "user"
    assert result[-1]["content"] == "current"
    # history should be trimmed
    total = sum(len(m["content"]) for m in result)
    assert total <= 150


def test_enforce_context_budget_compresses_system_last() -> None:
    messages = [
        {"role": "system", "content": "S" * 500},
        {"role": "user", "content": "hi"},
    ]
    # budget smaller than system alone
    result = enforce_context_budget(messages, total_char_budget=100)

    assert result[0]["role"] == "system"
    assert len(result[0]["content"]) <= 100
    assert result[-1]["content"] == "hi"


def test_enforce_context_budget_preserves_message_order() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
    ]
    result = enforce_context_budget(messages, total_char_budget=10000)

    roles = [m["role"] for m in result]
    assert roles == ["system", "user", "assistant", "user"]


def test_build_chat_messages_applies_context_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_prompt_builder(
        monkeypatch,
        settings_overrides={
            "prompt_soul_char_budget": 500,
            "prompt_system_char_budget": 120,
            "prompt_total_char_budget": 120,
        },
        workspace_overrides={"soul": "S" * 500},
        recent_messages=[
            {"role": "user", "content": "older question"},
            {"role": "assistant", "content": "older answer"},
        ],
    )

    result = build_chat_messages(
        user_message="current",
        request_context={"persona_id": "default"},
        session_messages=[],
    )

    assert len(result) == 2
    assert result[0]["role"] == "system"
    assert result[-1] == {"role": "user", "content": "current"}


def test_build_chat_messages_omits_tool_instructions_for_direct_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_prompt_builder(monkeypatch)

    result = build_chat_messages(
        user_message="你好",
        request_context={"persona_id": "default"},
        session_messages=[],
        allow_tools=False,
    )

    system_prompt = result[0]["content"]
    assert "search_knowledge" not in system_prompt
    assert "search_memory" not in system_prompt
    assert "save_memory" not in system_prompt


def test_build_chat_messages_includes_tool_instructions_for_tool_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_prompt_builder(monkeypatch)

    result = build_chat_messages(
        user_message="請幫我查一下知識庫",
        request_context={"persona_id": "default"},
        session_messages=[],
        allow_tools=True,
    )

    system_prompt = result[0]["content"]
    assert "search_knowledge" in system_prompt
    assert "search_memory" in system_prompt
    assert "save_memory" in system_prompt


# --- enforce_session_limits tests ---


def _stub_memory_for_guardrails(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Stub memory.memory so guardrails' lazy import works without FlagEmbedding."""
    from conftest import stub_chat_service_deps

    stub_chat_service_deps(monkeypatch)
    return sys.modules["memory.memory"]


def test_enforce_session_round_limit_raises_when_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_memory = _stub_memory_for_guardrails(monkeypatch)
    fake_memory.get_session_updated_at = lambda session_id, persona_id, project_id="default": None
    fake_memory.list_session_messages = lambda session_id, persona_id, project_id="default": [{"role": "user"}] * 100

    with pytest.raises(ValueError, match="輪上限"):
        guardrails.enforce_session_limits("sess_full", "default")


def test_enforce_session_round_within_limit_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_memory = _stub_memory_for_guardrails(monkeypatch)
    fake_memory.get_session_updated_at = lambda session_id, persona_id, project_id="default": None
    fake_memory.list_session_messages = lambda session_id, persona_id, project_id="default": [{"role": "user"}] * 5

    # should not raise
    guardrails.enforce_session_limits("sess_ok", "default")


def test_enforce_session_limits_rejects_expired_session(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_memory = _stub_memory_for_guardrails(monkeypatch)
    expired_at = (datetime.now(UTC) - timedelta(minutes=45)).isoformat(timespec="seconds")
    fake_memory.get_session_updated_at = lambda session_id, persona_id, project_id="default": expired_at
    fake_memory.list_session_messages = lambda session_id, persona_id, project_id="default": []

    # Override TTL to 30 minutes so the 45-minute-old session is expired
    monkeypatch.setattr(
        guardrails,
        "get_settings",
        lambda: type("Cfg", (), {
            "max_session_ttl_minutes": 30,
            "max_session_rounds": 100,
            "request_rate_limit_per_minute": 60,
            "resolved_allowed_channels": {"web"},
            "enable_content_filter": False,
            "block_prompt_injection": False,
        })(),
    )

    with pytest.raises(ValueError, match="TTL"):
        guardrails.enforce_session_limits("sess_expired", "default")


# --- chat service integration tests ---


def test_prepare_generation_skips_rag_for_direct_route(monkeypatch: pytest.MonkeyPatch) -> None:
    chat_service = _load_chat_service(monkeypatch)
    monkeypatch.setattr(
        chat_service,
        "enforce_guardrails",
        lambda action, text, context: None,
    )
    monkeypatch.setattr(
        chat_service,
        "enforce_session_limits",
        lambda session_id, persona_id, project_id="default": None,
    )
    monkeypatch.setattr(
        chat_service,
        "route_message",
        lambda brain_message: RouteDecision(path="direct", skip_rag=True, skip_tools=True),
    )
    monkeypatch.setattr(
        chat_service,
        "get_or_create_session",
        lambda session_id, persona_id, project_id="default": SimpleNamespace(session_id=session_id or "sess_new"),
    )
    monkeypatch.setattr(
        chat_service,
        "list_session_messages",
        lambda session_id, persona_id, project_id="default": [],
    )
    monkeypatch.setattr(
        chat_service,
        "append_session_message",
        lambda session_id, persona_id, role, content, project_id="default": None,
    )
    monkeypatch.setattr(
        chat_service,
        "build_chat_messages",
        lambda **kwargs: [{"role": "system", "content": "sys"}, {"role": "user", "content": kwargs["user_message"]}],
    )

    context = chat_service.prepare_generation(_make_envelope(message_type="control"))

    assert context.prompt_messages is not None


def test_prepare_generation_preserves_original_slash_message_in_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_service = _load_chat_service(monkeypatch)
    appended_messages: list[tuple[str, str, str, str]] = []
    prompt_user_messages: list[str] = []

    monkeypatch.setattr(chat_service, "enforce_guardrails", lambda action, text, context: None)
    monkeypatch.setattr(
        chat_service,
        "enforce_session_limits",
        lambda session_id, persona_id, project_id="default": None,
    )
    monkeypatch.setattr(
        chat_service,
        "route_message",
        lambda brain_message: RouteDecision(path="rag", skip_rag=False, skip_tools=False),
    )
    monkeypatch.setattr(
        chat_service,
        "get_or_create_session",
        lambda session_id, persona_id, project_id="default": SimpleNamespace(session_id=session_id or "sess_new"),
    )
    monkeypatch.setattr(chat_service, "list_session_messages", lambda session_id, persona_id, project_id="default": [])
    monkeypatch.setattr(
        chat_service,
        "append_session_message",
        lambda session_id, persona_id, role, content, project_id="default": appended_messages.append(
            (session_id, persona_id, role, content)
        ),
    )
    monkeypatch.setattr(
        chat_service,
        "build_chat_messages",
        lambda **kwargs: prompt_user_messages.append(kwargs["user_message"]) or [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": kwargs["user_message"]},
        ],
    )

    envelope = _make_envelope(content="[系統指令] 請立即呼叫工具 `joke:get_joke`，使用者的輸入為：黑色笑話")
    from protocol.message_envelope import METADATA_ORIGINAL_USER_MESSAGE
    envelope.context.metadata[METADATA_ORIGINAL_USER_MESSAGE] = "/joke 黑色笑話"

    context = chat_service.prepare_generation(envelope)

    assert appended_messages == [("sess_test", "default", "user", "/joke 黑色笑話")]
    assert prompt_user_messages == ["[系統指令] 請立即呼叫工具 `joke:get_joke`，使用者的輸入為：黑色笑話"]
    assert context.user_message == "/joke 黑色笑話"


def test_execute_generation_skips_tool_loop_for_direct_route(monkeypatch: pytest.MonkeyPatch) -> None:
    chat_service = _load_chat_service(monkeypatch)
    agent_loop = sys.modules["core.agent_loop"]
    monkeypatch.setattr(
        chat_service,
        "run_agent_loop",
        lambda messages, persona_id="default": (_ for _ in ()).throw(
            AssertionError("run_agent_loop should be skipped for direct route")
        ),
    )
    monkeypatch.setattr(
        chat_service,
        "generate_chat_reply",
        lambda messages: "direct reply",
        raising=False,
    )

    context = type(
        "GenerationContextLike",
        (),
        {
            "prompt_messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
            "persona_id": "default",
            "route": RouteDecision(path="direct", skip_rag=True, skip_tools=True),
        },
    )()

    result = chat_service.execute_generation(context)

    assert result == agent_loop.AgentLoopResult(reply="direct reply", tool_steps=[])

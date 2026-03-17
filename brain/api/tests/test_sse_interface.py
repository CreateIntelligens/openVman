from __future__ import annotations

import importlib
import json
import sys
import types
from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from core.pipeline import RouteDecision
from core.sse_events import (
    ContextEvent,
    DoneEvent,
    SessionEvent,
    TokenEvent,
    ToolEvent,
    build_exception_protocol_error,
    build_protocol_error,
    protocol_error_code_for_exception,
    sse_error_to_dict,
    sse_event_to_dict,
)
from protocol.protocol_events import validate_server_event


def _load_chat_service(monkeypatch: pytest.MonkeyPatch):
    from conftest import make_fake_agent_loop, stub_chat_service_deps

    stub_chat_service_deps(monkeypatch)
    monkeypatch.setitem(sys.modules, "core.agent_loop", make_fake_agent_loop())

    fake_llm_client = types.ModuleType("core.llm_client")
    fake_llm_client.generate_chat_reply = lambda messages: "sync reply"

    async def _stream_chat_reply(messages):
        for token in ("default",):
            yield token

    fake_llm_client.stream_chat_reply = _stream_chat_reply
    monkeypatch.setitem(sys.modules, "core.llm_client", fake_llm_client)

    sys.modules.pop("core.chat_service", None)
    return importlib.import_module("core.chat_service")


def _stub_finalize_dependencies(monkeypatch: pytest.MonkeyPatch, chat_service) -> None:
    monkeypatch.setattr(chat_service, "append_session_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_service, "archive_session_turn", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_service, "maybe_run_memory_maintenance", lambda project_id="default": {})
    monkeypatch.setattr(chat_service, "list_session_messages", lambda session_id, persona_id, project_id="default": [])


def _make_generation_context(
    chat_service,
    *,
    trace_id: str,
    session_id: str,
    route: RouteDecision,
    user_message: str,
    prompt_messages: list[dict[str, str]],
):
    return chat_service.GenerationContext(
        trace_id=trace_id,
        persona_id="default",
        project_id="default",
        session_id=session_id,
        route=route,
        user_message=user_message,
        request_context={"channel": "web"},
        prompt_messages=prompt_messages,
    )


@pytest.mark.parametrize(
    ("event_cls", "kwargs", "mutable_field"),
    [
        (SessionEvent, {"session_id": "s1", "trace_id": "t1"}, "session_id"),
        (
            ContextEvent,
            {
                "trace_id": "t1",
                "knowledge_count": 1,
                "memory_count": 2,
                "request_context": {"channel": "web"},
            },
            "knowledge_count",
        ),
        (
            ToolEvent,
            {
                "trace_id": "t1",
                "tool_call_id": "call_1",
                "name": "get_weather",
                "arguments": "{}",
                "result": "sunny",
            },
            "name",
        ),
        (TokenEvent, {"trace_id": "t1", "token": "hi"}, "token"),
        (
            DoneEvent,
            {
                "trace_id": "t1",
                "session_id": "s1",
                "reply": "done",
                "knowledge_results": [],
                "memory_results": [],
                "tool_steps": [],
            },
            "reply",
        ),
    ],
)
def test_sse_event_types_are_frozen_and_slotted(event_cls, kwargs, mutable_field):
    event = event_cls(**kwargs)

    assert is_dataclass(event)
    assert hasattr(event_cls, "__slots__")
    with pytest.raises(FrozenInstanceError):
        setattr(event, mutable_field, "changed")


def test_sse_payload_events_all_carry_trace_id():
    events = [
        SessionEvent(session_id="s1", trace_id="t1"),
        ContextEvent(trace_id="t1", knowledge_count=0, memory_count=0, request_context={}),
        ToolEvent(trace_id="t1", tool_call_id="call_1", name="tool", arguments="{}", result="ok"),
        TokenEvent(trace_id="t1", token="hi"),
        DoneEvent(
            trace_id="t1",
            session_id="s1",
            reply="done",
            knowledge_results=[],
            memory_results=[],
            tool_steps=[],
        ),
    ]

    assert all(event.trace_id == "t1" for event in events)


def test_sse_event_to_dict_uses_trace_as_event_id():
    payload = sse_event_to_dict(TokenEvent(trace_id="trace_123", token="hello"))

    assert payload["event"] == "token"
    assert payload["id"] == "trace_123"
    assert json.loads(payload["data"]) == {
        "trace_id": "trace_123",
        "token": "hello",
    }


def test_protocol_error_helpers_validate_and_map_session_errors():
    payload = build_protocol_error("BRAIN_UNAVAILABLE", "message 不可為空")

    validated = validate_server_event(payload)
    assert validated.error_code == "BRAIN_UNAVAILABLE"
    assert protocol_error_code_for_exception("session 已超過 TTL 30 分鐘") == "SESSION_EXPIRED"
    assert protocol_error_code_for_exception("message 不可為空") == "BRAIN_UNAVAILABLE"


def test_sse_error_to_dict_keeps_trace_and_contract_payload():
    error_payload = build_protocol_error("SESSION_EXPIRED", "session 已超過 TTL 30 分鐘")

    result = sse_error_to_dict(error_payload, "trace_err")

    assert result["event"] == "error"
    assert result["id"] == "trace_err"
    assert json.loads(result["data"]) == error_payload


@pytest.mark.asyncio
async def test_stream_generation_skip_tools_uses_native_stream(monkeypatch: pytest.MonkeyPatch):
    chat_service = _load_chat_service(monkeypatch)

    async def fake_stream(messages):
        assert messages == [{"role": "user", "content": "hi"}]
        for token in ("Hello", " world"):
            yield token

    monkeypatch.setattr(chat_service, "stream_chat_reply", fake_stream)
    monkeypatch.setattr(
        chat_service,
        "prepare_agent_reply",
        lambda messages, persona_id="default": (_ for _ in ()).throw(
            AssertionError("prepare_agent_reply should not run for direct route")
        ),
    )
    _stub_finalize_dependencies(monkeypatch, chat_service)

    context = _make_generation_context(
        chat_service,
        trace_id="trace_direct",
        session_id="sess_direct",
        route=RouteDecision(path="direct", skip_rag=True, skip_tools=True),
        user_message="hi",
        prompt_messages=[{"role": "user", "content": "hi"}],
    )

    events = [event async for event in chat_service.stream_generation(context)]

    assert [event.event for event in events] == ["session", "context", "token", "token", "done"]
    assert events[-1].reply == "Hello world"
    assert all(event.trace_id == "trace_direct" for event in events)


@pytest.mark.asyncio
async def test_stream_generation_with_tools_uses_native_stream_after_tool_phase(
    monkeypatch: pytest.MonkeyPatch,
):
    chat_service = _load_chat_service(monkeypatch)
    prepared_reply_cls = sys.modules["core.agent_loop"].PreparedAgentReply

    async def immediate_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    async def fake_stream(messages):
        assert messages[-1]["role"] == "tool"
        assert messages[-1]["content"] == "Sunny"
        for token in ("Final", " answer"):
            yield token

    monkeypatch.setattr(chat_service.asyncio, "to_thread", immediate_to_thread)
    monkeypatch.setattr(chat_service, "stream_chat_reply", fake_stream)
    monkeypatch.setattr(
        chat_service,
        "prepare_agent_reply",
        lambda messages, persona_id="default", project_id="default": prepared_reply_cls(
            messages=[
                *messages,
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "name": "get_weather",
                    "content": "Sunny",
                },
            ],
            tool_steps=[
                {
                    "tool_call_id": "call_1",
                    "name": "get_weather",
                    "arguments": '{"city":"Taipei"}',
                    "result": "Sunny",
                }
            ],
        ),
    )
    monkeypatch.setattr(
        chat_service,
        "run_agent_loop",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("stream_generation should not fall back to run_agent_loop chunks")
        ),
    )
    _stub_finalize_dependencies(monkeypatch, chat_service)

    context = _make_generation_context(
        chat_service,
        trace_id="trace_tool",
        session_id="sess_tool",
        route=RouteDecision(path="tool", skip_rag=True, skip_tools=False),
        user_message="weather in Taipei",
        prompt_messages=[{"role": "user", "content": "weather in Taipei"}],
    )

    events = [event async for event in chat_service.stream_generation(context)]

    # Context event is emitted after tool phase so counts reflect actual tool usage
    assert [event.event for event in events] == ["session", "tool", "context", "token", "token", "done"]
    assert events[1].trace_id == "trace_tool"
    assert events[1].name == "get_weather"
    assert events[-1].reply == "Final answer"
    assert events[-1].tool_steps == [
        {
            "tool_call_id": "call_1",
            "name": "get_weather",
            "arguments": '{"city":"Taipei"}',
            "result": "Sunny",
        }
    ]


@pytest.mark.asyncio
async def test_stream_generation_error_yields_no_done_event(monkeypatch: pytest.MonkeyPatch):
    chat_service = _load_chat_service(monkeypatch)

    async def failing_stream(messages):
        yield "partial"
        raise RuntimeError("LLM connection lost")

    monkeypatch.setattr(chat_service, "stream_chat_reply", failing_stream)
    _stub_finalize_dependencies(monkeypatch, chat_service)

    context = _make_generation_context(
        chat_service,
        trace_id="trace_err",
        session_id="sess_err",
        route=RouteDecision(path="direct", skip_rag=True, skip_tools=True),
        user_message="hi",
        prompt_messages=[{"role": "user", "content": "hi"}],
    )

    with pytest.raises(RuntimeError, match="LLM connection lost"):
        _ = [event async for event in chat_service.stream_generation(context)]


def test_build_exception_protocol_error_maps_session_errors():
    error = build_exception_protocol_error(ValueError("session 已達 100 輪上限"))

    assert error["error_code"] == "SESSION_EXPIRED"
    assert error["event"] == "server_error"
    validate_server_event(error)


def test_build_exception_protocol_error_maps_validation_errors():
    error = build_exception_protocol_error(ValueError("message 不可為空"))

    assert error["error_code"] == "BRAIN_UNAVAILABLE"
    assert error["event"] == "server_error"
    validate_server_event(error)

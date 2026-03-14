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
    fake_agent_loop = types.ModuleType("core.agent_loop")

    class AgentLoopResult:
        def __init__(self, reply: str, tool_steps: list[dict]):
            self.reply = reply
            self.tool_steps = tool_steps

    class PreparedAgentReply:
        def __init__(self, messages: list[dict], tool_steps: list[dict]):
            self.messages = messages
            self.tool_steps = tool_steps

    fake_agent_loop.AgentLoopResult = AgentLoopResult
    fake_agent_loop.PreparedAgentReply = PreparedAgentReply
    fake_agent_loop.run_agent_loop = lambda messages, persona_id="default": AgentLoopResult(
        reply="sync reply",
        tool_steps=[],
    )
    fake_agent_loop.prepare_agent_reply = lambda messages, persona_id="default": PreparedAgentReply(
        messages=list(messages),
        tool_steps=[],
    )

    fake_llm_client = types.ModuleType("core.llm_client")
    fake_llm_client.generate_chat_reply = lambda messages: "sync reply"

    async def _stream_chat_reply(messages):
        for token in ("default",):
            yield token

    fake_llm_client.stream_chat_reply = _stream_chat_reply

    fake_embedder = types.ModuleType("memory.embedder")
    fake_embedder.encode_text = lambda text: [0.1]

    fake_retrieval = types.ModuleType("memory.retrieval")
    fake_retrieval.search_records = lambda *args, **kwargs: []

    fake_memory = types.ModuleType("memory.memory")
    fake_memory.append_session_message = lambda session_id, persona_id, role, content: None
    fake_memory.archive_session_turn = lambda session_id, user_message, assistant_message, persona_id="default": None
    fake_memory.get_or_create_session = lambda session_id=None, persona_id="default": type(
        "Session",
        (),
        {"session_id": session_id or "sess_new"},
    )()
    fake_memory.list_session_messages = lambda session_id, persona_id=None: []

    fake_learnings = types.ModuleType("infra.learnings")
    fake_learnings.capture_learnings_from_message = lambda user_message: []
    fake_learnings.record_error_event = lambda area, summary, detail="": None

    fake_governance = types.ModuleType("memory.memory_governance")
    fake_governance.maybe_run_memory_maintenance = lambda: {"status": "skipped"}

    monkeypatch.setitem(sys.modules, "core.agent_loop", fake_agent_loop)
    monkeypatch.setitem(sys.modules, "core.llm_client", fake_llm_client)
    monkeypatch.setitem(sys.modules, "memory.embedder", fake_embedder)
    monkeypatch.setitem(sys.modules, "memory.retrieval", fake_retrieval)
    monkeypatch.setitem(sys.modules, "memory.memory", fake_memory)
    monkeypatch.setitem(sys.modules, "infra.learnings", fake_learnings)
    monkeypatch.setitem(sys.modules, "memory.memory_governance", fake_governance)
    sys.modules.pop("core.chat_service", None)
    return importlib.import_module("core.chat_service")


def _stub_finalize_dependencies(monkeypatch: pytest.MonkeyPatch, chat_service) -> None:
    monkeypatch.setattr(chat_service, "append_session_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_service, "archive_session_turn", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_service, "capture_learnings_from_message", lambda message: [])
    monkeypatch.setattr(chat_service, "maybe_run_memory_maintenance", lambda: {})
    monkeypatch.setattr(chat_service, "list_session_messages", lambda session_id, persona_id: [])


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
        session_id=session_id,
        route=route,
        user_message=user_message,
        request_context={"channel": "web"},
        prompt_messages=prompt_messages,
        knowledge_results=[],
        memory_results=[],
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
        lambda messages, persona_id="default": prepared_reply_cls(
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

    assert [event.event for event in events] == ["session", "context", "tool", "token", "token", "done"]
    assert events[2].trace_id == "trace_tool"
    assert events[2].name == "get_weather"
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

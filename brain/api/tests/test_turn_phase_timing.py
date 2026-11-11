"""每輪準備階段要記到分段時間：壓測時 10 人多出的 5 秒就是因為這段沒紀錄才查不出來。"""

from __future__ import annotations

import asyncio
import types
from unittest.mock import MagicMock

import pytest

import core.chat_service as chat_service
import routes.chat as chat_route
import safety.observability as observability


@pytest.fixture
def events(monkeypatch):
    captured: list[dict[str, object]] = []

    def capture(event: str, **fields: object) -> None:
        captured.append({"event": event, **fields})

    monkeypatch.setattr(observability, "log_event", capture)
    return captured


def nodes(events: list[dict[str, object]]) -> list[object]:
    return [event["node"] for event in events if event["event"] == "node_attempt"]


def test_every_event_carries_millisecond_time(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(observability.logger, "info", lines.append)
    observability.log_event("x")
    assert '"ts_ms": ' in lines[0]


def test_timed_node_records_success(events):
    with observability.timed_node("step", trace_id="t1"):
        pass
    assert events[0]["node"] == "step"
    assert events[0]["outcome"] == "ok"
    assert events[0]["trace_id"] == "t1"


def test_timed_node_records_failure_and_reraises(events):
    with pytest.raises(ValueError):
        with observability.timed_node("step", trace_id="t1"):
            raise ValueError("boom")
    assert events[0]["outcome"] == "error"


def test_worker_thread_wait_is_separate_from_the_step(events):
    request = types.SimpleNamespace(state=types.SimpleNamespace(trace_id="t1"))

    result = asyncio.run(chat_route._to_thread_timed(request, "prepare", lambda a: a + 1, 1))

    assert result == 2
    assert nodes(events) == ["chat_thread_wait", "chat_prepare"]
    assert events[0]["step"] == "prepare"
    assert {event["trace_id"] for event in events} == {"t1"}


def test_prepare_generation_times_each_step(events, monkeypatch):
    for name in ("enforce_guardrails", "enforce_session_limits", "route_message", "normalize_to_brain_message"):
        monkeypatch.setattr(chat_service, name, MagicMock())
    route = types.SimpleNamespace(skip_tools=False, forced_tool_name=None)
    monkeypatch.setattr(chat_service, "route_message", lambda _message: route)
    monkeypatch.setattr(
        chat_service, "get_or_create_session",
        lambda *_a, **_k: types.SimpleNamespace(session_id="s1"),
    )
    monkeypatch.setattr(chat_service, "list_session_messages", lambda *_a, **_k: [])
    monkeypatch.setattr(chat_service, "serialize_context", lambda _context: {})
    monkeypatch.setattr(chat_service, "build_chat_messages", lambda **_k: [])
    monkeypatch.setattr(chat_service, "turn_decision_config", lambda cfg: cfg)
    monkeypatch.setattr(
        chat_service, "get_tool_registry",
        lambda: types.SimpleNamespace(build_openai_tools=lambda: []),
    )
    decision = types.SimpleNamespace(
        policy=types.SimpleNamespace(dominant_language="zh"), dependency_unavailable=False,
    )
    monkeypatch.setattr(chat_service, "run_turn_decision", lambda **_k: decision)
    monkeypatch.setattr(chat_service, "without_disabled_recall", lambda d, *_a: d)
    monkeypatch.setattr("knowledge.kb_settings.primary_language", lambda _project: "zh")
    envelope = types.SimpleNamespace(
        content="問題",
        context=types.SimpleNamespace(
            metadata={}, persona_id="p", project_id="proj", session_id="s1",
            trace_id="t1", message_type="user",
        ),
    )

    chat_service.prepare_generation(envelope)

    assert nodes(events) == [
        "chat_guardrails", "chat_session_load", "chat_turn_decision", "chat_build_prompt",
    ]
    assert {event["trace_id"] for event in events} == {"t1"}

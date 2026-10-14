"""A chat whose HTTP caller disconnected must stop before its next LLM or tool step.

使用者打斷數位人時前端會 abort fetch；以前 Brain 照樣把整輪 LLM、工具跑完，
還把回答寫進對話紀錄。
"""

from __future__ import annotations

import asyncio
import importlib
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.generation_cancel import (
    GenerationCancelled,
    bind_cancel_event,
    is_cancelled,
)


def _cancelled_event() -> threading.Event:
    event = threading.Event()
    event.set()
    return event


# ---------------------------------------------------------------------------
# Agent loop safe points
# ---------------------------------------------------------------------------

_SEARCH_TOOL_SPEC = {
    "type": "function",
    "function": {"name": "search_knowledge", "description": "kb", "parameters": {}},
}


@pytest.fixture
def agent_loop(monkeypatch: pytest.MonkeyPatch):
    module = importlib.import_module("core.agent_loop")
    registry = MagicMock()
    registry.build_openai_tools.return_value = [_SEARCH_TOOL_SPEC]
    monkeypatch.setattr(module, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(
        module, "bind_tool_context",
        lambda *args, **kwargs: MagicMock(
            __enter__=lambda s: s, __exit__=lambda s, *a: None,
        ),
    )
    cfg = MagicMock()
    cfg.agent_loop_max_rounds = 4
    cfg.chat_force_knowledge_search = False
    cfg.chat_answer_pass_excludes_knowledge_search = False
    cfg.chat_prefetch_knowledge_search = False
    cfg.forced_tool_model_override = ""
    cfg.chat_max_followup_tool_rounds = 1
    cfg.forced_tool_max_tokens = 200
    monkeypatch.setattr(module, "get_settings", lambda: cfg)
    return module


def _tool_turn(agent_loop: Any) -> Any:
    return agent_loop.LLMReply(
        content="",
        tool_calls=[agent_loop.LLMToolCall(
            id="c1", name="search_knowledge", arguments="{}", extra_content=None,
        )],
        model="m1",
    )


def _wire_turns(monkeypatch, agent_loop, replies, on_call=None) -> list[str]:
    calls: list[str] = []
    queue = list(replies)

    def turn(messages, tools=None, **kwargs):
        calls.append("llm")
        reply = queue.pop(0)
        if on_call is not None:
            on_call(len(calls))
        return reply

    monkeypatch.setattr(agent_loop, "stream_chat_turn", turn)
    monkeypatch.setattr(agent_loop, "generate_chat_turn", turn)
    return calls


def test_disconnect_before_generation_makes_no_llm_call(monkeypatch, agent_loop):
    calls = _wire_turns(monkeypatch, agent_loop, [])

    with bind_cancel_event(_cancelled_event()), pytest.raises(GenerationCancelled) as info:
        agent_loop.run_agent_loop([{"role": "user", "content": "門診時間？"}])

    assert calls == []
    assert info.value.stage == "llm_round_0"


def test_disconnect_during_llm_call_skips_the_tool_round(monkeypatch, agent_loop):
    event = threading.Event()
    calls = _wire_turns(
        monkeypatch, agent_loop, [_tool_turn(agent_loop)],
        # 模型回應期間用戶端離開：這次呼叫收不回來，但工具不該再跑。
        on_call=lambda _n: event.set(),
    )
    tool_calls: list[str] = []
    monkeypatch.setattr(
        agent_loop, "execute_tool_call",
        lambda name, args: tool_calls.append(name) or "{}",
    )

    with bind_cancel_event(event), pytest.raises(GenerationCancelled) as info:
        agent_loop.run_agent_loop([{"role": "user", "content": "門診時間？"}])

    assert calls == ["llm"]
    assert tool_calls == []
    assert info.value.stage == "tool_round_0"


def test_disconnect_during_tool_round_skips_the_next_llm_call(monkeypatch, agent_loop):
    event = threading.Event()
    calls = _wire_turns(
        monkeypatch, agent_loop,
        [_tool_turn(agent_loop), agent_loop.LLMReply(content="答案", tool_calls=[], model="m1")],
    )

    def tool(name, args):
        event.set()
        return "{}"

    monkeypatch.setattr(agent_loop, "execute_tool_call", tool)

    with bind_cancel_event(event), pytest.raises(GenerationCancelled) as info:
        agent_loop.run_agent_loop([{"role": "user", "content": "門診時間？"}])

    assert calls == ["llm"]
    assert info.value.stage == "llm_round_1"
    assert info.value.tool_steps == 1


def test_unbound_or_unset_event_leaves_the_loop_unchanged(monkeypatch, agent_loop):
    calls = _wire_turns(
        monkeypatch, agent_loop,
        [_tool_turn(agent_loop), agent_loop.LLMReply(content="答案", tool_calls=[], model="m1")],
    )
    monkeypatch.setattr(agent_loop, "execute_tool_call", lambda name, args: "{}")

    with bind_cancel_event(threading.Event()):
        result = agent_loop.run_agent_loop([{"role": "user", "content": "門診時間？"}])

    assert result.reply == "答案"
    assert calls == ["llm", "llm"]
    assert not is_cancelled()


# ---------------------------------------------------------------------------
# LLM client: between streamed chunks and before fallback hops
# ---------------------------------------------------------------------------

def _chunk(text: str) -> Any:
    delta = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(
        usage=None, choices=[SimpleNamespace(delta=delta, finish_reason=None)],
    )


class _Stream:
    def __init__(self, chunks: list[Any], on_chunk=None) -> None:
        self._chunks = chunks
        self._on_chunk = on_chunk
        self.sent = 0
        self.closed = False

    def __iter__(self):
        for chunk in self._chunks:
            self.sent += 1
            yield chunk
            if self._on_chunk is not None:
                self._on_chunk(self.sent)

    def close(self) -> None:
        self.closed = True


def test_stream_stops_between_chunks_and_closes_the_provider_stream():
    llm_client = importlib.import_module("core.llm_client")
    event = threading.Event()
    stream = _Stream(
        [_chunk("一"), _chunk("二"), _chunk("三")],
        on_chunk=lambda n: event.set() if n == 1 else None,
    )

    with bind_cancel_event(event), pytest.raises(GenerationCancelled) as info:
        llm_client._consume_stream(stream, model="m1")

    # 第二段到達時發現已取消；第三段不再向 provider 要。
    assert stream.sent == 2
    assert stream.closed is True
    assert info.value.stage == "llm_stream"


@pytest.fixture
def two_hop_client(monkeypatch: pytest.MonkeyPatch):
    llm_client = importlib.import_module("core.llm_client")
    hops = [
        SimpleNamespace(
            api_key=f"k{i}", base_url=None, model=f"m{i}", provider="test", hop_index=i,
        )
        for i in range(2)
    ]
    clients: dict[str, MagicMock] = {}

    def client_for(api_key, base_url):
        return clients.setdefault(api_key, MagicMock())

    monkeypatch.setattr(llm_client, "_require_api_key", lambda: None)
    monkeypatch.setattr(llm_client, "_get_gemini_client", lambda: None)
    monkeypatch.setattr(
        llm_client, "_resolve_chain_or_routes", lambda tid, client=None: (hops, []),
    )
    monkeypatch.setattr(llm_client, "get_provider_router", lambda: MagicMock())
    monkeypatch.setattr(llm_client, "get_settings", lambda: MagicMock(llm_temperature=0.3))
    monkeypatch.setattr(llm_client, "_get_sync_client", client_for)
    failures: list[Any] = []
    monkeypatch.setattr(
        llm_client, "_record_hop_failure",
        lambda hop, exc, *args: failures.append((hop.model, exc)) or "error",
    )
    return llm_client, clients, failures


def test_cancelled_turn_never_reaches_the_provider(two_hop_client):
    llm_client, clients, failures = two_hop_client

    with bind_cancel_event(_cancelled_event()):
        with pytest.raises(GenerationCancelled):
            llm_client.generate_chat_turn([{"role": "user", "content": "hi"}])
        with pytest.raises(GenerationCancelled):
            llm_client.stream_chat_turn([{"role": "user", "content": "hi"}])

    assert clients == {}
    assert failures == []


def test_cancel_mid_stream_is_not_a_hop_failure_and_skips_fallback(
    two_hop_client, monkeypatch,
):
    llm_client, clients, failures = two_hop_client
    event = threading.Event()

    def first_client(api_key, base_url):
        client = clients.setdefault(api_key, MagicMock())
        client.chat.completions.create.return_value = _Stream(
            [_chunk("一"), _chunk("二")], on_chunk=lambda n: event.set(),
        )
        return client

    monkeypatch.setattr(llm_client, "_get_sync_client", first_client)

    with bind_cancel_event(event), pytest.raises(GenerationCancelled):
        llm_client.stream_chat_turn([{"role": "user", "content": "hi"}])

    # 斷線不是 provider 故障：不記失敗、不換下一站重試。
    assert list(clients) == ["k0"]
    assert failures == []


# ---------------------------------------------------------------------------
# /brain/chat route: watch the client, never persist a cancelled turn
# ---------------------------------------------------------------------------

@pytest.fixture
def chat_route(monkeypatch: pytest.MonkeyPatch):
    from routes import chat as module

    observed: dict[str, Any] = {
        "events": [], "finalize": [], "stage": [], "media": [], "errors": [],
    }
    monkeypatch.setattr(
        module, "log_event",
        lambda event, **fields: observed["events"].append((event, fields)),
    )
    monkeypatch.setattr(
        module, "_handle_generation_error",
        lambda exc, action, request: observed["errors"].append(exc),
    )
    monkeypatch.setattr(
        module, "_prepare_chat_context",
        lambda request, payload: SimpleNamespace(
            trace_id="trace-1", project_id="default", session_id="s1",
            persona_id="default", request_context={}, turn_decision=None,
        ),
    )
    monkeypatch.setattr(
        module, "finalize_generation",
        lambda *args, **kwargs: observed["finalize"].append(args) or {"status": "ok"},
    )
    monkeypatch.setattr(
        module, "stage_turn",
        lambda *args, **kwargs: observed["stage"].append(args) or {"status": "ok"},
    )
    monkeypatch.setattr(module, "register_turn", lambda request, payload: None)
    monkeypatch.setattr(
        module, "reply_media",
        lambda context, steps: observed["media"].append(steps) or None,
    )
    return module, observed


class _Request:
    """Just enough of a Starlette request; the client leaves after *leave_after* seconds."""

    def __init__(self, leave_after: float | None) -> None:
        self.headers: dict[str, str] = {}
        self.state = SimpleNamespace(trace_id="trace-1")
        self.scope: dict[str, Any] = {}
        self._leave_at = leave_after

    async def is_disconnected(self) -> bool:
        if self._leave_at is None:
            return False
        loop = asyncio.get_running_loop()
        if not hasattr(self, "_start"):
            self._start = loop.time()
        return loop.time() - self._start >= self._leave_at


def _payload(**overrides: Any) -> Any:
    from protocol.schemas import ChatRequest

    return ChatRequest(message="門診時間？", session_id="s1", **overrides)


def _wait_then_check(stage: str):
    """Stand-in for the agent loop: block until cancelled, then hit a safe point."""
    from core.generation_cancel import raise_if_cancelled

    def generate(context):
        for _ in range(200):
            if is_cancelled():
                break
            threading.Event().wait(0.01)
        raise_if_cancelled(stage, tool_steps=1)
        return SimpleNamespace(reply="不該送出", tool_steps=[])

    return generate


@pytest.mark.parametrize("turn_fields", [{}, {"turn_id": "t1", "turn_revision": 1}])
def test_disconnect_stops_generation_and_persists_nothing(
    chat_route, monkeypatch, turn_fields,
):
    module, observed = chat_route
    monkeypatch.setattr(module, "execute_generation", _wait_then_check("llm_round_1"))

    response = asyncio.run(module.chat(_Request(leave_after=0.05), _payload(**turn_fields)))

    assert response.status_code == 499
    assert observed["finalize"] == []
    assert observed["stage"] == []
    assert observed["media"] == []
    assert observed["errors"] == []
    [(event, fields)] = observed["events"]
    assert event == "chat_cancelled"
    assert fields["trace_id"] == "trace-1"
    assert fields["stage"] == "llm_round_1"
    assert fields["tool_steps"] == 1


def test_answer_finished_after_disconnect_is_not_persisted(chat_route, monkeypatch):
    module, observed = chat_route

    def generate(context):
        # 最後一次 LLM 呼叫收不回來，斷線後才跑完。
        for _ in range(200):
            if is_cancelled():
                break
            threading.Event().wait(0.01)
        return SimpleNamespace(reply="答案", tool_steps=[])

    monkeypatch.setattr(module, "execute_generation", generate)

    response = asyncio.run(module.chat(_Request(leave_after=0.05), _payload()))

    assert response.status_code == 499
    assert observed["finalize"] == []
    assert observed["media"] == []
    assert observed["events"][0][1]["stage"] == "reply_media"


def test_disconnect_during_turn_decision_is_a_cancel_not_a_failure(chat_route, monkeypatch):
    from core.decision_router import DecisionProviderCancelled
    from core.generation_cancel import current_cancel_event

    module, observed = chat_route
    seen: list[Any] = []

    def prepare(request, payload):
        event = current_cancel_event()
        seen.append(event)
        assert event is not None and event.wait(2)
        raise DecisionProviderCancelled("decision turn was cancelled")

    monkeypatch.setattr(module, "_prepare_chat_context", prepare)

    response = asyncio.run(module.chat(_Request(leave_after=0.05), _payload()))

    assert response.status_code == 499
    assert observed["errors"] == []
    assert observed["events"][0][1]["stage"] == "turn_decision"


def test_connected_client_gets_the_normal_reply(chat_route, monkeypatch):
    module, observed = chat_route
    monkeypatch.setattr(
        module, "execute_generation",
        lambda context: SimpleNamespace(reply="答案", tool_steps=[]),
    )

    response = asyncio.run(module.chat(_Request(leave_after=None), _payload()))

    assert response["status"] == "ok"
    assert len(observed["finalize"]) == 1
    assert [event for event, _ in observed["events"]] == ["chat_complete"]

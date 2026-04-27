"""Tests for TASK-27: Tool error handling and reinjection into stream."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from conftest import load_tool_modules
from safety.observability import MetricsStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_result(result_json: str) -> dict[str, object]:
    return json.loads(result_json)


def _make_tool(tool_registry, *, name: str = "test_tool", handler=None, parameters=None):
    if handler is None:
        handler = lambda args: {"ok": True}
    if parameters is None:
        parameters = {"type": "object", "properties": {}}
    return tool_registry.Tool(name, "desc", parameters, handler)


def _stub_heavy_modules(monkeypatch: pytest.MonkeyPatch):
    """Stub out modules that need native libs (FlagEmbedding, etc.).

    Returns the freshly-loaded ``core.chat_service`` module so that tests
    get the correct ``ToolPhaseError`` class identity.
    """
    from conftest import stub_chat_service_deps

    stub_chat_service_deps(monkeypatch)

    # Force re-import so chat_service picks up the real core.agent_loop
    sys.modules.pop("core.chat_service", None)
    sys.modules.pop("tools.tool_executor", None)
    sys.modules.pop("tools.tool_registry", None)
    import importlib
    return importlib.import_module("core.chat_service")


def _load_agent_loop(monkeypatch: pytest.MonkeyPatch):
    fake_embedder = types.ModuleType("memory.embedder")
    fake_embedder.encode_text = lambda text, embedding_version=None: [0.1]
    fake_embedder.encode_query_with_fallback = lambda query, *, project_id="default", table_names=("knowledge", "memories"): types.SimpleNamespace(
        version="bge",
        vector=[0.1],
        attempted_versions=[{"version": "bge", "status": "selected"}],
    )

    fake_retrieval = types.ModuleType("memory.retrieval")
    fake_retrieval.search_records = lambda *a, **kw: []

    monkeypatch.setitem(sys.modules, "memory.embedder", fake_embedder)
    monkeypatch.setitem(sys.modules, "memory.retrieval", fake_retrieval)
    sys.modules.pop("core.agent_loop", None)
    sys.modules.pop("tools.tool_executor", None)
    sys.modules.pop("tools.tool_registry", None)

    import importlib
    return importlib.import_module("core.agent_loop")


# ---------------------------------------------------------------------------
# Step 1: Per-tool timeout
# ---------------------------------------------------------------------------

class TestToolCallTimeout:
    def test_execute_tool_call_timeout_returns_quickly(self, monkeypatch: pytest.MonkeyPatch):
        """timeout 不會真的等 handler 結束"""
        tool_registry, tool_executor = load_tool_modules(monkeypatch)
        registry = tool_registry.ToolRegistry()

        def slow_handler(args: dict[str, Any]) -> dict[str, Any]:
            time.sleep(30)
            return {"ok": True}

        registry.register(_make_tool(tool_registry, name="slow", handler=slow_handler))

        fake_settings = MagicMock()
        fake_settings.tool_call_timeout_seconds = 1

        monkeypatch.setattr(tool_executor, "get_tool_registry", lambda: registry)
        monkeypatch.setattr(tool_executor, "get_settings", lambda: fake_settings)
        monkeypatch.setattr(tool_executor, "log_event", lambda event, **kw: None)

        started = time.perf_counter()
        result = _decode_result(tool_executor.execute_tool_call("slow", {}))
        elapsed = time.perf_counter() - started

        assert elapsed < 3
        assert result["status"] == "error"

    def test_execute_tool_call_timeout_returns_error(self, monkeypatch: pytest.MonkeyPatch):
        """handler sleep(30) + timeout=1 → ToolResult error 含「逾時」"""
        tool_registry, tool_executor = load_tool_modules(monkeypatch)
        registry = tool_registry.ToolRegistry()

        def slow_handler(args: dict[str, Any]) -> dict[str, Any]:
            time.sleep(30)
            return {"ok": True}

        registry.register(_make_tool(tool_registry, name="slow", handler=slow_handler))
        metrics = MetricsStore()

        fake_settings = MagicMock()
        fake_settings.tool_call_timeout_seconds = 1

        monkeypatch.setattr(tool_executor, "get_tool_registry", lambda: registry)
        monkeypatch.setattr(tool_executor, "get_settings", lambda: fake_settings)
        monkeypatch.setattr(tool_executor, "get_metrics_store", lambda: metrics)
        monkeypatch.setattr(tool_executor, "log_event", lambda event, **kw: None)

        result = _decode_result(tool_executor.execute_tool_call("slow", {}))

        assert result["status"] == "error"
        assert "逾時" in result["error"]

    def test_execute_tool_call_timeout_records_metrics(self, monkeypatch: pytest.MonkeyPatch):
        """timeout 後 metrics counter status=timeout 有計數"""
        tool_registry, tool_executor = load_tool_modules(monkeypatch)
        registry = tool_registry.ToolRegistry()

        def slow_handler(args: dict[str, Any]) -> dict[str, Any]:
            time.sleep(30)
            return {"ok": True}

        registry.register(_make_tool(tool_registry, name="slow", handler=slow_handler))
        metrics = MetricsStore()
        events: list[tuple[str, dict[str, object]]] = []

        fake_settings = MagicMock()
        fake_settings.tool_call_timeout_seconds = 1

        monkeypatch.setattr(tool_executor, "get_tool_registry", lambda: registry)
        monkeypatch.setattr(tool_executor, "get_settings", lambda: fake_settings)
        monkeypatch.setattr(tool_executor, "get_metrics_store", lambda: metrics)
        monkeypatch.setattr(
            tool_executor,
            "log_event",
            lambda event, **fields: events.append((event, fields)),
        )

        tool_executor.execute_tool_call("slow", {})

        snapshot = metrics.snapshot()
        assert snapshot["counters"]["tool_calls_total|status=timeout,tool_name=slow"] == 1
        timeout_events = [e for e in events if e[0] == "tool_timeout"]
        assert len(timeout_events) == 1


# ---------------------------------------------------------------------------
# Step 2: ToolPhaseError + agent loop
# ---------------------------------------------------------------------------

class TestToolPhaseError:
    def test_run_agent_loop_max_rounds_raises_tool_phase_error(self, monkeypatch: pytest.MonkeyPatch):
        """永遠回 tool_calls → ToolPhaseError（非 ValueError）"""
        agent_loop = _load_agent_loop(monkeypatch)

        fake_tool_call = agent_loop.LLMToolCall(
            id="call_1", name="test", arguments="{}", extra_content=None,
        )
        fake_turn = agent_loop.LLMReply(
            content="", tool_calls=[fake_tool_call], model="test-model",
        )

        monkeypatch.setattr(agent_loop, "stream_chat_turn", lambda msgs, tools=None, **kw: fake_turn)
        monkeypatch.setattr(agent_loop, "generate_chat_turn", lambda msgs, tools=None, **kw: fake_turn)
        monkeypatch.setattr(agent_loop, "execute_tool_call", lambda name, args: '{"status":"ok","tool_name":"test","data":{},"error":""}')

        fake_registry = MagicMock()
        fake_registry.build_openai_tools.return_value = []
        monkeypatch.setattr(agent_loop, "get_tool_registry", lambda: fake_registry)
        monkeypatch.setattr(agent_loop, "bind_tool_context", lambda pid, proj="default": MagicMock(__enter__=lambda s: s, __exit__=lambda s, *a: None))

        fake_cfg = MagicMock()
        fake_cfg.agent_loop_max_rounds = 2
        monkeypatch.setattr(agent_loop, "get_settings", lambda: fake_cfg)

        with pytest.raises(agent_loop.ToolPhaseError) as exc_info:
            agent_loop.run_agent_loop([{"role": "user", "content": "hi"}])

        assert "最大輪次" in str(exc_info.value)

    def test_tool_phase_error_carries_partial_steps(self, monkeypatch: pytest.MonkeyPatch):
        """ToolPhaseError.partial_steps 包含已完成的步驟"""
        agent_loop = _load_agent_loop(monkeypatch)

        call_count = 0

        def fake_generate(msgs, tools=None, **kw):
            nonlocal call_count
            call_count += 1
            return agent_loop.LLMReply(
                content="",
                tool_calls=[agent_loop.LLMToolCall(
                    id=f"call_{call_count}", name="test", arguments="{}", extra_content=None,
                )],
                model="test-model",
            )

        monkeypatch.setattr(agent_loop, "stream_chat_turn", fake_generate)
        monkeypatch.setattr(agent_loop, "generate_chat_turn", fake_generate)
        monkeypatch.setattr(agent_loop, "execute_tool_call", lambda name, args: '{"status":"ok","tool_name":"test","data":{},"error":""}')

        fake_registry = MagicMock()
        fake_registry.build_openai_tools.return_value = []
        monkeypatch.setattr(agent_loop, "get_tool_registry", lambda: fake_registry)
        monkeypatch.setattr(agent_loop, "bind_tool_context", lambda pid, proj="default": MagicMock(__enter__=lambda s: s, __exit__=lambda s, *a: None))

        fake_cfg = MagicMock()
        fake_cfg.agent_loop_max_rounds = 3
        monkeypatch.setattr(agent_loop, "get_settings", lambda: fake_cfg)

        with pytest.raises(agent_loop.ToolPhaseError) as exc_info:
            agent_loop.run_agent_loop([{"role": "user", "content": "hi"}])

        assert len(exc_info.value.partial_steps) == 3
        assert len(exc_info.value.partial_messages) > 0


# ---------------------------------------------------------------------------
# Step 5: stream_chat_turn iteration dispatch
# ---------------------------------------------------------------------------

class TestStreamChatTurnIterationDispatch:
    def test_no_tool_message_uses_single_stream_call(self, monkeypatch: pytest.MonkeyPatch):
        """Non-tool message: only stream_chat_turn called (iteration 0), no _generate_turn."""
        agent_loop = _load_agent_loop(monkeypatch)

        text_turn = agent_loop.LLMReply(content="hello", tool_calls=[], model="m1")

        stream_calls: list[int] = []
        generate_calls: list[int] = []

        def fake_stream(msgs, tools=None, **kw):
            stream_calls.append(1)
            return text_turn

        def fake_generate(msgs, tools=None, **kw):
            generate_calls.append(1)
            return text_turn

        monkeypatch.setattr(agent_loop, "stream_chat_turn", fake_stream)
        monkeypatch.setattr(agent_loop, "generate_chat_turn", fake_generate)
        monkeypatch.setattr(agent_loop, "execute_tool_call", lambda name, args: '{"status":"ok","tool_name":"test","data":{},"error":""}')

        fake_registry = MagicMock()
        fake_registry.build_openai_tools.return_value = []
        monkeypatch.setattr(agent_loop, "get_tool_registry", lambda: fake_registry)
        monkeypatch.setattr(agent_loop, "bind_tool_context", lambda pid, proj="default": MagicMock(__enter__=lambda s: s, __exit__=lambda s, *a: None))

        fake_cfg = MagicMock()
        fake_cfg.agent_loop_max_rounds = 3
        monkeypatch.setattr(agent_loop, "get_settings", lambda: fake_cfg)

        result = agent_loop.run_agent_loop([{"role": "user", "content": "早安"}])

        assert result.reply == "hello"
        assert len(stream_calls) == 1
        assert len(generate_calls) == 0

    def test_tool_use_message_uses_stream_then_generate(self, monkeypatch: pytest.MonkeyPatch):
        """Tool-use: stream_chat_turn on iteration 0, _generate_turn on iteration 1."""
        agent_loop = _load_agent_loop(monkeypatch)

        tool_turn = agent_loop.LLMReply(
            content="",
            tool_calls=[agent_loop.LLMToolCall(id="c1", name="do_thing", arguments="{}", extra_content=None)],
            model="m1",
        )
        text_turn = agent_loop.LLMReply(content="done", tool_calls=[], model="m1")

        stream_calls: list[int] = []
        generate_calls: list[int] = []

        def fake_stream(msgs, tools=None, **kw):
            stream_calls.append(1)
            return tool_turn

        def fake_generate(msgs, tools=None, **kw):
            generate_calls.append(1)
            return text_turn

        monkeypatch.setattr(agent_loop, "stream_chat_turn", fake_stream)
        monkeypatch.setattr(agent_loop, "generate_chat_turn", fake_generate)
        monkeypatch.setattr(agent_loop, "execute_tool_call", lambda name, args: '{"status":"ok","tool_name":"do_thing","data":{},"error":""}')

        fake_registry = MagicMock()
        fake_registry.build_openai_tools.return_value = []
        monkeypatch.setattr(agent_loop, "get_tool_registry", lambda: fake_registry)
        monkeypatch.setattr(agent_loop, "bind_tool_context", lambda pid, proj="default": MagicMock(__enter__=lambda s: s, __exit__=lambda s, *a: None))

        fake_cfg = MagicMock()
        fake_cfg.agent_loop_max_rounds = 3
        monkeypatch.setattr(agent_loop, "get_settings", lambda: fake_cfg)

        result = agent_loop.run_agent_loop([{"role": "user", "content": "do something"}])

        assert result.reply == "done"
        assert len(stream_calls) == 1
        assert len(generate_calls) == 1


# ---------------------------------------------------------------------------
# Step 3: ToolErrorEvent
# ---------------------------------------------------------------------------

class TestToolErrorEvent:
    def test_tool_error_event_frozen(self):
        """ToolErrorEvent is frozen dataclass"""
        from core.sse_events import ToolErrorEvent

        evt = ToolErrorEvent(
            trace_id="t1",
            error="boom",
            partial_steps_count=2,
            tool_call_id="call_1",
            name="query_order",
            status="timeout",
        )

        assert evt.trace_id == "t1"
        assert evt.error == "boom"
        assert evt.status == "timeout"

        with pytest.raises(AttributeError):
            evt.error = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Step 4: Graceful degradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def test_inject_tool_fallback_hint_immutable(self, monkeypatch: pytest.MonkeyPatch):
        """回傳新 list，原 list 不變"""
        chat_service = _stub_heavy_modules(monkeypatch)

        original = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        original_copy = list(original)

        result = chat_service._inject_tool_fallback_hint(original)

        assert original == original_copy
        assert len(result) == len(original) + 1
        assert result[-2]["role"] == "system"
        assert "工具流程部分失敗" in result[-2]["content"]

    def test_execute_generation_falls_back_on_tool_phase_error(self, monkeypatch: pytest.MonkeyPatch):
        """run_agent_loop raise → fallback reply + partial_steps"""
        chat_service = _stub_heavy_modules(monkeypatch)
        ToolPhaseError = chat_service.ToolPhaseError

        partial = [{"tool_call_id": "c1", "name": "t", "arguments": "{}", "result": "{}"}]
        partial_messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": None, "tool_calls": []},
            {"role": "tool", "tool_call_id": "c1", "name": "t", "content": "{}"},
        ]

        monkeypatch.setattr(
            chat_service,
            "run_agent_loop",
            MagicMock(
                side_effect=ToolPhaseError(
                    "max rounds",
                    partial_steps=partial,
                    partial_messages=partial_messages,
                )
            ),
        )
        seen_messages: list[dict[str, Any]] = []
        monkeypatch.setattr(
            chat_service,
            "generate_chat_turn",
            lambda msgs, **kwargs: (
                seen_messages.extend(msgs),
                types.SimpleNamespace(
                    content="fallback answer",
                    tool_calls=[],
                    model="test-model",
                    pii_report=None,
                ),
            )[1],
        )

        fake_route = MagicMock()
        fake_route.skip_tools = False

        ctx = MagicMock()
        ctx.route = fake_route
        ctx.prompt_messages = [{"role": "user", "content": "hi"}]
        ctx.persona_id = "default"

        result = chat_service.execute_generation(ctx)

        assert result.reply == "fallback answer"
        assert result.tool_steps == partial
        assert any(message.get("role") == "tool" for message in seen_messages)
        assert any("工具流程部分失敗" in str(message.get("content", "")) for message in seen_messages)


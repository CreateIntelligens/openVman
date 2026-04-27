"""Unit tests for stream_chat_turn() in llm_client."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


# ---------------------------------------------------------------------------
# Minimal chunk/delta mock helpers
# ---------------------------------------------------------------------------

class _FunctionDelta:
    def __init__(self, name: str | None = None, arguments: str | None = None):
        self.name = name
        self.arguments = arguments


class _ToolCallDelta:
    def __init__(self, index: int, id: str | None = None, name: str | None = None, arguments: str | None = None):
        self.index = index
        self.id = id
        self.function = _FunctionDelta(name, arguments)


class _Delta:
    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[_ToolCallDelta] | None = None,
    ):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, delta: _Delta, finish_reason: str | None = None):
        self.delta = delta
        self.finish_reason = finish_reason


class _Chunk:
    def __init__(self, choice: _Choice):
        self.choices = [choice]


def _text_chunks(tokens: list[str], *, model: str = "m1") -> list[_Chunk]:
    """Build a list of streaming chunks that deliver a text response."""
    chunks = [
        _Chunk(_Choice(_Delta(content=tok)))
        for tok in tokens
    ]
    chunks.append(_Chunk(_Choice(_Delta(), finish_reason="stop")))
    return chunks


def _tool_chunks(
    *,
    call_id: str = "call_abc",
    name: str = "do_thing",
    args: str = '{"x": 1}',
    index: int = 0,
) -> list[_Chunk]:
    """Build streaming chunks that deliver a single tool call."""
    return [
        _Chunk(_Choice(_Delta(tool_calls=[_ToolCallDelta(index, id=call_id, name=name)]))),
        _Chunk(_Choice(_Delta(tool_calls=[_ToolCallDelta(index, arguments=args)]))),
        _Chunk(_Choice(_Delta(), finish_reason="tool_calls")),
    ]


# ---------------------------------------------------------------------------
# Dependency stubs
# ---------------------------------------------------------------------------

def _stub_deps(monkeypatch: pytest.MonkeyPatch):
    """Stub the observability and privacy modules that llm_client imports."""
    fake_obs = types.ModuleType("safety.observability")
    fake_obs.record_route_attempt = MagicMock()
    fake_obs.record_fallback_hop = MagicMock()
    fake_obs.record_chain_exhausted = MagicMock()
    fake_obs.log_event = MagicMock()
    fake_obs.log_exception = MagicMock()
    fake_obs.MetricsStore = MagicMock
    fake_obs.get_metrics_store = MagicMock()
    fake_obs.record_circuit_state_change = MagicMock()
    monkeypatch.setitem(sys.modules, "safety.observability", fake_obs)

    fake_learnings = types.ModuleType("infra.learnings")
    fake_learnings.record_error_event = MagicMock()
    monkeypatch.setitem(sys.modules, "infra.learnings", fake_learnings)

    for mod in ("core.key_pool", "core.provider_router", "core.fallback_chain", "core.llm_client"):
        sys.modules.pop(mod, None)

    return importlib.import_module("core.llm_client")


def _stub_config(monkeypatch: pytest.MonkeyPatch, llm_client: Any, *, api_key: str = "k1", model: str = "m1"):
    """Wire a minimal settings + chain stub into llm_client."""
    fake_cfg = MagicMock()
    fake_cfg.llm_temperature = 0.3
    fake_cfg.resolved_llm_api_keys = [api_key]
    fake_cfg.resolved_fallback_chain = [("test", model)]
    fake_cfg.llm_provider = "test"
    fake_cfg.llm_model = model
    fake_cfg.llm_api_key = api_key
    fake_cfg.llm_api_keys = ""
    fake_cfg.llm_base_url = ""
    fake_cfg.llm_fallback_model = ""
    fake_cfg.llm_fallback_chain = f"test:{model}"
    fake_cfg.llm_max_fallback_hops = 4
    fake_cfg.llm_key_cooldown_seconds = 60
    fake_cfg.llm_key_long_cooldown_seconds = 300
    fake_cfg.gemini_api_key = ""
    fake_cfg.groq_api_key = ""
    fake_cfg.openai_api_key = ""
    fake_cfg.resolve_base_url_for_provider = lambda p: ""
    fake_cfg.resolve_api_key_for_provider = lambda p: api_key if p == "test" else ""
    fake_cfg.resolved_llm_base_url = ""
    fake_cfg.resolved_llm_models = [model]

    import config
    config._settings = None
    monkeypatch.setattr(config, "get_settings", lambda: fake_cfg)
    monkeypatch.setattr(llm_client, "get_settings", lambda: fake_cfg)

    fake_privacy = types.ModuleType("privacy.filter")
    fake_privacy.detect_llm_messages_pii = lambda messages, source="unknown", trace_id="": None
    fake_privacy.FilterSource = str
    fake_privacy.PiiDetectionReport = None
    monkeypatch.setitem(sys.modules, "privacy.filter", fake_privacy)
    llm_client._PII_EXECUTOR.submit = lambda fn, *a, **kw: None


# ---------------------------------------------------------------------------
# 3.1: Text-only response
# ---------------------------------------------------------------------------

class TestStreamChatTurnTextResponse:
    def test_text_response_returns_llm_reply_with_content(self, monkeypatch: pytest.MonkeyPatch):
        """Text-only stream → LLMReply(content=<text>, tool_calls=[])"""
        llm_client = _stub_deps(monkeypatch)
        _stub_config(monkeypatch, llm_client, model="m1")

        chunks = _text_chunks(["Hello", ", ", "world!"])

        with patch("core.llm_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = iter(chunks)
            mock_openai.return_value = mock_client

            reply = llm_client.stream_chat_turn(
                [{"role": "user", "content": "hi"}],
                trace_id="t-text",
            )

        assert reply.content == "Hello, world!"
        assert reply.tool_calls == []

    def test_whitespace_only_content_is_stripped_to_empty(self, monkeypatch: pytest.MonkeyPatch):
        """Whitespace-only accumulated text → content stripped to \"\"."""
        llm_client = _stub_deps(monkeypatch)
        _stub_config(monkeypatch, llm_client, model="m1")

        chunks = _text_chunks(["  ", "\n", "  "])

        with patch("core.llm_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = iter(chunks)
            mock_openai.return_value = mock_client

            reply = llm_client.stream_chat_turn(
                [{"role": "user", "content": "hi"}],
                trace_id="t-ws",
            )

        assert reply.content == ""
        assert reply.tool_calls == []


# ---------------------------------------------------------------------------
# 3.2: Tool call response
# ---------------------------------------------------------------------------

class TestStreamChatTurnToolCallResponse:
    def test_tool_call_response_assembled_correctly(self, monkeypatch: pytest.MonkeyPatch):
        """Tool-call stream → LLMReply(content=\"\", tool_calls=[...]) with correct fields."""
        llm_client = _stub_deps(monkeypatch)
        _stub_config(monkeypatch, llm_client, model="m1")

        chunks = _tool_chunks(call_id="call_xyz", name="search", args='{"q": "test"}')

        with patch("core.llm_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = iter(chunks)
            mock_openai.return_value = mock_client

            reply = llm_client.stream_chat_turn(
                [{"role": "user", "content": "search something"}],
                trace_id="t-tool",
            )

        assert reply.content == ""
        assert len(reply.tool_calls) == 1
        tc = reply.tool_calls[0]
        assert tc.id == "call_xyz"
        assert tc.name == "search"
        assert tc.arguments == '{"q": "test"}'


# ---------------------------------------------------------------------------
# 3.3: Multiple tool calls
# ---------------------------------------------------------------------------

class TestStreamChatTurnMultipleToolCalls:
    def test_multiple_tool_calls_assembled_in_index_order(self, monkeypatch: pytest.MonkeyPatch):
        """Two tool calls with distinct index values → both returned in index order."""
        llm_client = _stub_deps(monkeypatch)
        _stub_config(monkeypatch, llm_client, model="m1")

        # index=0: call_a / tool_a, index=1: call_b / tool_b (interleaved like OpenAI sends)
        chunks = [
            _Chunk(_Choice(_Delta(tool_calls=[_ToolCallDelta(0, id="call_a", name="tool_a")]))),
            _Chunk(_Choice(_Delta(tool_calls=[_ToolCallDelta(1, id="call_b", name="tool_b")]))),
            _Chunk(_Choice(_Delta(tool_calls=[_ToolCallDelta(0, arguments='{"p": 1}')]))),
            _Chunk(_Choice(_Delta(tool_calls=[_ToolCallDelta(1, arguments='{"q": 2}')]))),
            _Chunk(_Choice(_Delta(), finish_reason="tool_calls")),
        ]

        with patch("core.llm_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = iter(chunks)
            mock_openai.return_value = mock_client

            reply = llm_client.stream_chat_turn(
                [{"role": "user", "content": "do two things"}],
                trace_id="t-multi",
            )

        assert len(reply.tool_calls) == 2
        assert reply.tool_calls[0].id == "call_a"
        assert reply.tool_calls[0].name == "tool_a"
        assert reply.tool_calls[0].arguments == '{"p": 1}'
        assert reply.tool_calls[1].id == "call_b"
        assert reply.tool_calls[1].name == "tool_b"
        assert reply.tool_calls[1].arguments == '{"q": 2}'


# ---------------------------------------------------------------------------
# 3.4: Empty stream raises ValueError
# ---------------------------------------------------------------------------

class TestStreamChatTurnEmptyResponse:
    def test_empty_stream_raises_value_error(self, monkeypatch: pytest.MonkeyPatch):
        """Stream ends with no content and no tool calls → ValueError."""
        llm_client = _stub_deps(monkeypatch)
        _stub_config(monkeypatch, llm_client, model="m1")

        chunks = [_Chunk(_Choice(_Delta(), finish_reason="stop"))]

        with patch("core.llm_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = iter(chunks)
            mock_openai.return_value = mock_client

            with pytest.raises(ValueError, match="LLM 沒有回傳內容"):
                llm_client.stream_chat_turn(
                    [{"role": "user", "content": "hi"}],
                    trace_id="t-empty",
                )

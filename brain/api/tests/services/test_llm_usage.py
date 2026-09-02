"""Usage capture in llm_client: non-stream responses and streaming usage chunks."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "test_stream_chat_turn_helpers", Path(__file__).with_name("test_stream_chat_turn.py"),
)
assert _spec is not None and _spec.loader is not None
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
_Chunk, _Choice, _Delta = _helpers._Chunk, _helpers._Choice, _helpers._Delta
_stub_config, _stub_deps = _helpers._stub_config, _helpers._stub_deps


class _UsageChunk:
    """Final chunk emitted with stream_options.include_usage: no choices, only usage."""

    def __init__(self, prompt: int, completion: int) -> None:
        self.choices = []
        self.usage = SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
            prompt_tokens_details=None,
            completion_tokens_details=None,
        )


def test_consume_stream_captures_trailing_usage_chunk(monkeypatch: pytest.MonkeyPatch):
    llm_client = _stub_deps(monkeypatch)
    chunks = [
        _Chunk(_Choice(_Delta(content="哈"))),
        _Chunk(_Choice(_Delta(content="囉"))),
        _Chunk(_Choice(_Delta(), finish_reason="stop")),
        _UsageChunk(11, 2),
    ]
    reply = llm_client._consume_stream(iter(chunks), model="m1")
    assert reply.content == "哈囉"
    assert reply.usage is not None
    assert (reply.usage.input_tokens, reply.usage.output_tokens) == (11, 2)


def test_consume_stream_without_usage_leaves_none(monkeypatch: pytest.MonkeyPatch):
    llm_client = _stub_deps(monkeypatch)
    chunks = [_Chunk(_Choice(_Delta(content="x"))), _Chunk(_Choice(_Delta(), finish_reason="stop"))]
    assert llm_client._consume_stream(iter(chunks), model="m1").usage is None


def test_stream_chat_turn_requests_usage_and_records(monkeypatch: pytest.MonkeyPatch):
    llm_client = _stub_deps(monkeypatch)
    _stub_config(monkeypatch, llm_client)
    recorded: list[dict] = []
    monkeypatch.setattr(
        llm_client, "record_usage_event", lambda **kw: recorded.append(kw) or kw,
    )

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = iter([
        _Chunk(_Choice(_Delta(content="ok"))),
        _Chunk(_Choice(_Delta(), finish_reason="stop")),
        _UsageChunk(5, 1),
    ])
    monkeypatch.setattr(llm_client, "_get_sync_client", lambda *a, **k: fake_client)

    reply = llm_client.stream_chat_turn([{"role": "user", "content": "hi"}])

    assert reply.content == "ok"
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["stream"] is True
    assert kwargs["stream_options"] == {"include_usage": True}
    assert len(recorded) == 1
    assert recorded[0]["model"] == "m1"
    assert recorded[0]["usage"].total_tokens == 6


def test_stream_usage_flag_can_be_disabled(monkeypatch: pytest.MonkeyPatch):
    llm_client = _stub_deps(monkeypatch)
    assert llm_client._stream_usage_kwargs(SimpleNamespace(llm_stream_include_usage=False)) == {}
    assert llm_client._stream_usage_kwargs(SimpleNamespace()) == {
        "stream_options": {"include_usage": True},
    }


def test_generate_chat_turn_attaches_usage_and_records(monkeypatch: pytest.MonkeyPatch):
    llm_client = _stub_deps(monkeypatch)
    _stub_config(monkeypatch, llm_client)
    recorded: list[dict] = []
    monkeypatch.setattr(
        llm_client, "record_usage_event", lambda **kw: recorded.append(kw) or kw,
    )

    message = SimpleNamespace(content="answer", tool_calls=None)
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        model="m1",
        usage=SimpleNamespace(
            prompt_tokens=40,
            completion_tokens=8,
            total_tokens=48,
            prompt_tokens_details=SimpleNamespace(cached_tokens=30),
            completion_tokens_details=None,
        ),
    )
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = response
    monkeypatch.setattr(llm_client, "_get_sync_client", lambda *a, **k: fake_client)

    reply = llm_client.generate_chat_turn([{"role": "user", "content": "hi"}])

    assert reply.content == "answer"
    assert reply.usage is not None
    assert reply.usage.cached_tokens == 30
    assert recorded[0]["usage"].total_tokens == 48
    assert recorded[0]["provider"] == "test"

"""Tests for the Brain-owned Gemini Live session manager."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _load_module():
    fake_config = types.SimpleNamespace(
        gemini_api_key="test-key",
        live_gemini_model="gemini-3.1-flash-live-preview",
        live_gemini_system_instruction="",
        live_gemini_output_audio_transcription=True,
        live_gemini_tools_enabled=True,
        live_gemini_thinking_level="",
    )
    sys.modules["config"] = types.SimpleNamespace(
        BrainSettings=object,
        get_settings=lambda: fake_config,
    )
    sys.modules["memory.embedder"] = types.SimpleNamespace(
        encode_query_with_fallback=lambda *args, **kwargs: types.SimpleNamespace(
            version="bge",
            vector=[0.1, 0.2],
        )
    )
    sys.modules["memory.retrieval"] = types.SimpleNamespace(
        search_records=lambda *args, **kwargs: [{"text": "result"}]
    )
    sys.modules.pop("live.gemini_live", None)
    return importlib.import_module("live.gemini_live"), fake_config


class FakeTransport:
    def __init__(self) -> None:
        self.connect_calls = 0
        self.ping_calls = 0
        self.close_calls = 0
        self.sent_messages: list[dict] = []
        self._messages: asyncio.Queue[object] = asyncio.Queue()
        self._messages.put_nowait({"setupComplete": {}})

    async def connect(self) -> None:
        self.connect_calls += 1

    async def send_json(self, payload: dict) -> None:
        self.sent_messages.append(payload)

    async def recv_json(self) -> dict | None:
        item = await self._messages.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def ping(self) -> None:
        self.ping_calls += 1

    async def close(self) -> None:
        self.close_calls += 1
        return None


@pytest.mark.asyncio
async def test_gemini_live_session_reuses_transport_across_text_turns():
    module, fake_config = _load_module()
    transport = FakeTransport()
    emitted: list[dict] = []

    async def _sink(event: dict) -> None:
        emitted.append(event)

    session = module.GeminiLiveSession(
        relay_session_id="relay-1",
        client_id="client-1",
        config=fake_config,
        transport_factory=lambda _cfg: transport,
        event_sink=_sink,
    )

    await session.send_text_turn("你好")
    await session.send_text_turn("再說一次")
    await asyncio.sleep(0)
    await session.close()

    assert emitted == []
    assert transport.connect_calls == 1
    assert transport.close_calls == 1
    assert transport.sent_messages[0]["setup"]["model"] == "models/gemini-3.1-flash-live-preview"
    assert transport.sent_messages[1]["clientContent"]["turns"][0]["parts"][0]["text"] == "你好"
    assert transport.sent_messages[2]["clientContent"]["turns"][0]["parts"][0]["text"] == "再說一次"


@pytest.mark.asyncio
async def test_gemini_live_session_sends_realtime_input_and_turn_complete():
    module, fake_config = _load_module()
    transport = FakeTransport()
    emitted: list[dict] = []

    async def _sink(event: dict) -> None:
        emitted.append(event)

    session = module.GeminiLiveSession(
        relay_session_id="relay-audio",
        client_id="client-audio",
        config=fake_config,
        transport_factory=lambda _cfg: transport,
        event_sink=_sink,
    )

    await session.send_realtime_input("YWJj", "audio/pcm;rate=16000")
    await session.send_turn_complete()
    await session.close()

    assert emitted == []
    assert transport.connect_calls == 1
    assert transport.sent_messages[1] == {
        "realtimeInput": {
            "audio": {
                "mimeType": "audio/pcm;rate=16000",
                "data": "YWJj",
            }
        }
    }
    assert transport.sent_messages[2] == {"realtimeInput": {"audioStreamEnd": True}}


@pytest.mark.asyncio
async def test_gemini_live_session_reconnects_after_listener_failure(monkeypatch):
    module, fake_config = _load_module()
    first = FakeTransport()
    second = FakeTransport()
    transports = iter([first, second])
    emitted: list[dict] = []
    retry_delays: list[int] = []

    async def _sink(event: dict) -> None:
        emitted.append(event)

    async def _fake_sleep(delay: int) -> None:
        retry_delays.append(delay)

    monkeypatch.setattr(module, "_sleep_before_retry", _fake_sleep)

    session = module.GeminiLiveSession(
        relay_session_id="relay-2",
        client_id="client-2",
        config=fake_config,
        transport_factory=lambda _cfg: next(transports),
        event_sink=_sink,
    )

    await session.send_text_turn("你好")
    first._messages.put_nowait(RuntimeError("socket dropped"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await session.close()

    assert retry_delays == [1]
    assert first.connect_calls == 1
    assert second.connect_calls == 1
    assert emitted[0]["event"] == "server_stop_audio"
    assert emitted[0]["reason"] == "provider_reconnect"


@pytest.mark.asyncio
async def test_gemini_live_session_marks_transport_unavailable_after_max_retries(monkeypatch):
    module, fake_config = _load_module()
    first = FakeTransport()
    emitted: list[dict] = []
    retry_delays: list[int] = []

    class FailingReconnectTransport(FakeTransport):
        async def connect(self) -> None:
            raise RuntimeError("connect failed")

    async def _sink(event: dict) -> None:
        emitted.append(event)

    async def _fake_sleep(delay: int) -> None:
        retry_delays.append(delay)

    monkeypatch.setattr(module, "_sleep_before_retry", _fake_sleep)
    reconnect_attempts = [FailingReconnectTransport() for _ in range(5)]
    transports = iter([first, *reconnect_attempts])

    session = module.GeminiLiveSession(
        relay_session_id="relay-3",
        client_id="client-3",
        config=fake_config,
        transport_factory=lambda _cfg: next(transports),
        event_sink=_sink,
    )

    await session.send_text_turn("你好")
    first._messages.put_nowait(RuntimeError("socket dropped"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await session.close()

    assert retry_delays == [1, 2, 4, 8, 16]
    assert session._unavailable is True
    assert emitted[-1]["event"] == "server_error"
    assert "unavailable after reconnect retries" in emitted[-1]["message"]


@pytest.mark.asyncio
async def test_gemini_live_session_drops_audio_during_reconnect():
    module, fake_config = _load_module()
    transport = FakeTransport()
    emitted: list[dict] = []

    async def _sink(event: dict) -> None:
        emitted.append(event)

    session = module.GeminiLiveSession(
        relay_session_id="relay-4",
        client_id="client-4",
        config=fake_config,
        transport_factory=lambda _cfg: transport,
        event_sink=_sink,
    )

    session._reconnecting = True
    await session.send_realtime_input("YWJj", "audio/pcm;rate=16000")
    await session.close()

    assert emitted == []
    assert transport.sent_messages == []


@pytest.mark.asyncio
async def test_gemini_live_session_keepalive_pings_transport(monkeypatch):
    module, fake_config = _load_module()
    transport = FakeTransport()

    async def _sink(event: dict) -> None:
        return None

    session = module.GeminiLiveSession(
        relay_session_id="relay-keepalive",
        client_id="client-keepalive",
        config=fake_config,
        transport_factory=lambda _cfg: transport,
        event_sink=_sink,
    )
    session._transport = transport

    sleep_calls = 0

    async def _fake_sleep(delay: int) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        assert delay == module._KEEPALIVE_INTERVAL_SECONDS
        session._closed = True

    monkeypatch.setattr(module.asyncio, "sleep", _fake_sleep)

    await session._keepalive_loop()

    assert sleep_calls == 1
    assert transport.ping_calls == 1

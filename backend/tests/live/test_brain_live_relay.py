import asyncio
import json

import pytest

from app.gateway.brain_live_relay import BrainLiveRelay
from app.session_manager import Session


class FakeWebSocket:
    def __init__(self, relay: BrainLiveRelay, messages: list[str]) -> None:
        self._relay = relay
        self._messages = list(messages)

    async def recv(self) -> str:
        if not self._messages:
            raise AssertionError("recv called without queued messages")

        message = self._messages.pop(0)
        if not self._messages:
            self._clear_relay_socket()
        return message

    def _clear_relay_socket(self) -> None:
        self._relay._ws = None


class ConnectableFakeWebSocket:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []
        self.closed = False

    async def send(self, payload: str) -> None:
        self.sent_messages.append(json.loads(payload))

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_brain_live_relay_strips_audio_but_forwards_text():
    """Backend must strip upstream audio so the frontend's /tts_stream is the
    sole audio source (otherwise the user hears both voices)."""
    session = Session(client_id="client-1")
    emitted: list[dict[str, object]] = []

    async def sink(payload: dict[str, object]) -> None:
        emitted.append(payload)

    relay = BrainLiveRelay(session, event_sink=sink)
    payload = {
        "event": "server_stream_chunk",
        "chunk_id": "chunk-1",
        "session_id": session.session_id,
        "text": "原封轉發",
        "audio_base64": "Z2VtaW5pLWF1ZGlv",
        "is_final": True,
    }
    relay._ws = FakeWebSocket(relay, [json.dumps(payload)])

    await relay._listen()

    assert emitted == [{**payload, "audio_base64": ""}]


@pytest.mark.asyncio
async def test_brain_live_relay_forwards_non_chunk_events_unchanged():
    """Non server_stream_chunk events should pass through untouched."""
    session = Session(client_id="client-2")
    emitted: list[dict[str, object]] = []

    async def sink(payload: dict[str, object]) -> None:
        emitted.append(payload)

    relay = BrainLiveRelay(session, event_sink=sink)
    payload = {"event": "server_stop_audio", "session_id": session.session_id}
    relay._ws = FakeWebSocket(relay, [json.dumps(payload)])

    await relay._listen()

    assert emitted == [payload]


@pytest.mark.asyncio
async def test_brain_live_relay_serializes_initial_connect_under_concurrent_send():
    session = Session(client_id="client-concurrent")
    websocket = ConnectableFakeWebSocket()
    connect_calls = 0

    async def websocket_factory(*_args, **_kwargs):
        nonlocal connect_calls
        connect_calls += 1
        await asyncio.sleep(0)
        return websocket

    relay = BrainLiveRelay(
        session,
        websocket_factory=websocket_factory,
    )

    await asyncio.gather(
        relay.send_event({"event": "client_audio_chunk", "audio_base64": "YQ=="}),
        relay.send_event({"event": "client_audio_end"}),
    )
    await relay.close()

    assert connect_calls == 1
    assert [payload["event"] for payload in websocket.sent_messages] == [
        "relay_init",
        "client_audio_chunk",
        "client_audio_end",
    ]

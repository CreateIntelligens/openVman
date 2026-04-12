from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient


def _client() -> TestClient:
    from internal_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class FakeLiveSession:
    def __init__(self) -> None:
        self.text_turns: list[str] = []
        self.audio_chunks: list[tuple[str, str]] = []
        self.turn_complete_calls = 0
        self.stop_calls = 0
        self.close_calls = 0

    async def send_text_turn(self, text: str) -> None:
        self.text_turns.append(text)

    async def request_stop(self) -> None:
        self.stop_calls += 1

    async def send_realtime_input(self, audio_b64: str, mime_type: str) -> None:
        self.audio_chunks.append((audio_b64, mime_type))

    async def send_turn_complete(self) -> None:
        self.turn_complete_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


def test_internal_live_bridge_routes_text_audio_and_close():
    fake_session = FakeLiveSession()

    with (
        patch("internal_routes._build_live_session", return_value=fake_session) as build_live_session,
        patch(
            "internal_routes.get_or_create_session",
            return_value=type("Session", (), {"session_id": "relay-1"})(),
        ),
        patch("internal_routes.append_session_message"),
    ):
        with _client() as client:
            with client.websocket_connect("/brain/internal/live/relay-1") as websocket:
                websocket.send_json(
                    {
                        "event": "relay_init",
                        "client_id": "client-1",
                        "persona_id": "persona-1",
                        "project_id": "project-1",
                    }
                )
                websocket.send_json({"event": "user_speak", "text": "你好"})
                websocket.send_json(
                    {
                        "event": "client_audio_chunk",
                        "audio_base64": "YWJj",
                        "mime_type": "audio/pcm;rate=16000",
                    }
                )
                websocket.send_json({"event": "client_audio_end"})
                websocket.send_json({"event": "client_interrupt"})

    build_live_session.assert_called_once()
    assert fake_session.text_turns == ["你好"]
    assert fake_session.audio_chunks == [("YWJj", "audio/pcm;rate=16000")]
    assert fake_session.turn_complete_calls == 1
    assert fake_session.stop_calls == 1
    assert fake_session.close_calls == 1


@pytest.mark.asyncio
async def test_internal_live_bridge_event_sink_ignores_disconnected_websocket(monkeypatch):
    import internal_routes

    captured_sink = None

    class FakeLiveSessionForDisconnect:
        async def close(self) -> None:
            return None

    class FakeWebSocket:
        def __init__(self) -> None:
            self._messages = [
                {
                    "event": "relay_init",
                    "client_id": "client-1",
                    "persona_id": "persona-1",
                    "project_id": "project-1",
                }
            ]
            self.disconnected = False

        async def accept(self) -> None:
            return None

        async def receive_json(self) -> dict:
            if self._messages:
                return self._messages.pop(0)
            self.disconnected = True
            raise WebSocketDisconnect()

        async def send_json(self, _payload: dict) -> None:
            if self.disconnected:
                raise WebSocketDisconnect()

    def _fake_build_live_session(*_args, event_sink, **_kwargs):
        nonlocal captured_sink
        captured_sink = event_sink
        return FakeLiveSessionForDisconnect()

    monkeypatch.setattr(internal_routes, "_build_live_session", _fake_build_live_session)
    monkeypatch.setattr(
        internal_routes,
        "get_or_create_session",
        lambda *_args, **_kwargs: type("Session", (), {"session_id": "relay-disconnect"})(),
    )
    websocket = FakeWebSocket()

    await internal_routes.internal_live_bridge(websocket, "relay-disconnect")

    assert captured_sink is not None
    await captured_sink(
        {
            "event": "server_stop_audio",
            "session_id": "relay-disconnect",
            "timestamp": 123,
        }
    )
    await asyncio.sleep(0)

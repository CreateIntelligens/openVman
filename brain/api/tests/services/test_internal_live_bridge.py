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


def _internal_headers() -> dict[str, str]:
    from config import get_settings

    return {"X-Internal-Token": get_settings().gateway_internal_token}


class FakeLiveSession:
    def __init__(self) -> None:
        self.text_turns: list[str] = []
        self.audio_chunks: list[tuple[str, str]] = []
        self.turn_complete_calls = 0
        self.stop_calls = 0
        self.close_calls = 0

    async def send_text_turn(self, text: str, speech_language: str | None = None) -> None:
        self.text_turns.append(text)
        self.speech_languages = [*getattr(self, "speech_languages", []), speech_language]

    async def request_stop(self) -> None:
        self.stop_calls += 1

    async def send_realtime_input(self, audio_b64: str, mime_type: str) -> None:
        self.audio_chunks.append((audio_b64, mime_type))

    async def send_turn_complete(self) -> None:
        self.turn_complete_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


@pytest.mark.parametrize("principal_type,principal_id", [
    ("user", "account-1"), ("embed_key", "key-1"),
])
def test_internal_live_bridge_routes_text_audio_and_close(principal_type, principal_id):
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
            with client.websocket_connect(
                "/brain/internal/live/relay-1",
                headers={
                    **_internal_headers(),
                    "X-OpenVMan-User-ID": "account-1",
                    "X-OpenVMan-Role": "user",
                    "X-Principal-Type": principal_type,
                    "X-Principal-Id": principal_id,
                },
            ) as websocket:
                websocket.send_json(
                    {
                        "event": "relay_init",
                        "client_id": "client-1",
                        "persona_id": "persona-1",
                        "project_id": "project-1",
                        "user_id": "spoofed",
                        "principal_id": "spoofed",
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
    assert build_live_session.call_args.kwargs["user_id"] == "account-1"
    assert build_live_session.call_args.kwargs["principal_type"] == principal_type
    assert build_live_session.call_args.kwargs["principal_id"] == principal_id
    assert fake_session.text_turns == ["你好"]
    assert fake_session.audio_chunks == [("YWJj", "audio/pcm;rate=16000")]
    assert fake_session.turn_complete_calls == 1
    assert fake_session.stop_calls == 1
    assert fake_session.close_calls == 1


def test_internal_live_bridge_ephemeral_user_speak_not_persisted():
    """視覺脈絡以 ephemeral user_speak 餵入 live，餵給 AI 但不落歷史。"""
    fake_session = FakeLiveSession()

    with (
        patch("internal_routes._build_live_session", return_value=fake_session),
        patch(
            "internal_routes.get_or_create_session",
            return_value=type("Session", (), {"session_id": "relay-1"})(),
        ),
        patch("internal_routes.append_session_message") as append_msg,
    ):
        with _client() as client:
            with client.websocket_connect(
                "/brain/internal/live/relay-1",
                headers=_internal_headers(),
            ) as websocket:
                websocket.send_json(
                    {
                        "event": "relay_init",
                        "client_id": "client-1",
                        "persona_id": "persona-1",
                        "project_id": "project-1",
                    }
                )
                websocket.send_json(
                    {
                        "event": "user_speak",
                        "text": "[視覺事件] 畫面中出現一位訪客。",
                        "ephemeral": True,
                    }
                )

    # 餵給 AI（送出 text turn），但不存歷史
    assert fake_session.text_turns == ["[視覺事件] 畫面中出現一位訪客。"]
    append_msg.assert_not_called()


@pytest.mark.asyncio
async def test_internal_live_bridge_event_sink_ignores_disconnected_websocket(monkeypatch):
    import internal_routes

    captured_sink = None

    class FakeLiveSessionForDisconnect:
        async def close(self) -> None:
            return None

    class FakeWebSocket:
        def __init__(self) -> None:
            self.headers = _internal_headers()
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


@pytest.mark.asyncio
async def test_internal_live_bridge_rejects_invalid_internal_token_before_accept():
    import internal_routes

    class RejectingWebSocket:
        headers = {"X-Internal-Token": "wrong"}

        def __init__(self) -> None:
            self.accepted = False
            self.close_code = None

        async def accept(self) -> None:
            self.accepted = True

        async def close(self, code: int, reason: str) -> None:
            self.close_code = code
            self.close_reason = reason

    websocket = RejectingWebSocket()

    await internal_routes.internal_live_bridge(websocket, "relay-rejected")

    assert websocket.accepted is False
    assert websocket.close_code == 1008
    assert websocket.close_reason == "invalid internal token"


@pytest.mark.asyncio
async def test_internal_live_bridge_leaves_reply_persistence_to_live_session(monkeypatch):
    """回覆由 GeminiLiveSession 存；bridge 再存一次會讓每輪回覆重複一則。"""
    import internal_routes

    captured_sink = None
    saved: list[tuple] = []
    archived: list[dict] = []

    class FakeWebSocket:
        headers = _internal_headers()

        def __init__(self) -> None:
            self._messages = [{"event": "relay_init", "project_id": "project-1"}]

        async def accept(self) -> None:
            return None

        async def receive_json(self) -> dict:
            if self._messages:
                return self._messages.pop(0)
            await captured_sink({"event": "user_transcription", "text": "你好"})
            await captured_sink({"event": "server_stream_chunk", "text": "今天", "is_final": False})
            await captured_sink({"event": "server_stream_chunk", "text": "是星期三。", "is_final": True})
            raise WebSocketDisconnect()

        async def send_json(self, _payload: dict) -> None:
            return None

    class FakeLive:
        async def close(self) -> None:
            return None

    def _fake_build_live_session(*_args, event_sink, **_kwargs):
        nonlocal captured_sink
        captured_sink = event_sink
        return FakeLive()

    monkeypatch.setattr(internal_routes, "_build_live_session", _fake_build_live_session)
    monkeypatch.setattr(
        internal_routes,
        "get_or_create_session",
        lambda *_args, **_kwargs: type("Session", (), {"session_id": "relay-once"})(),
    )
    monkeypatch.setattr(internal_routes, "append_session_message", lambda *a, **kw: saved.append(a))
    import memory.memory as memory_module
    monkeypatch.setattr(memory_module, "archive_session_turn", lambda **kw: archived.append(kw))

    await internal_routes.internal_live_bridge(FakeWebSocket(), "relay-once")

    assert saved == []
    assert archived == []


def test_audio_language_endpoint_returns_verdict_and_survives_failure(monkeypatch):
    import memory.language_detect as language_detect

    monkeypatch.setattr(language_detect, "detect_audio_language", lambda wav: "nan")
    with _client() as client:
        ok = client.post("/brain/internal/audio-language", content=b"RIFFfake", headers=_internal_headers())
    assert ok.json() == {"language": "nan"}

    def boom(_wav):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(language_detect, "detect_audio_language", boom)
    with _client() as client:
        failed = client.post("/brain/internal/audio-language", content=b"RIFFfake", headers=_internal_headers())
    assert failed.json() == {"language": None}


def test_internal_live_bridge_passes_speech_language_to_history_and_live():
    """前台 ASR 聽出台語時帶 speech_language：存進訊息語言，也交給 Live 查台語文件。"""
    fake_session = FakeLiveSession()

    with (
        patch("internal_routes._build_live_session", return_value=fake_session),
        patch(
            "internal_routes.get_or_create_session",
            return_value=type("Session", (), {"session_id": "relay-1"})(),
        ),
        patch("internal_routes.append_session_message") as append_msg,
    ):
        with _client() as client:
            with client.websocket_connect(
                "/brain/internal/live/relay-1", headers=_internal_headers(),
            ) as websocket:
                websocket.send_json({"event": "relay_init", "project_id": "proj-hospital"})
                websocket.send_json(
                    {"event": "user_speak", "text": "我現在頭很痛", "speech_language": "nan"}
                )

    assert fake_session.speech_languages == ["nan"]
    assert append_msg.call_args.kwargs["language"] == "nan"

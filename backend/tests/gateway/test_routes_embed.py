"""Tests for public embed routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
import logging

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.gateway.auth_embed import EmbedAuthMiddleware, EmbedRateLimiter
from app.gateway.embed_keys import EmbedKeyStore
from app.gateway.ingestion import IngestionResult
from app.gateway import routes_embed


class FakeClock:
    def __init__(self) -> None:
        self.current = 1_700_000_000.0

    def __call__(self) -> float:
        return self.current


def _client(tmp_path):
    clock = FakeClock()
    store = EmbedKeyStore(tmp_path / "embed_keys.json", time_fn=clock)
    created = store.create(
        tenant_id="tenant-a",
        allowed_domains=["example.com"],
    )
    routes_embed._ws_key_store = store
    routes_embed._ws_rate_limiter = EmbedRateLimiter(time_fn=clock)
    app = FastAPI()
    app.add_middleware(
        EmbedAuthMiddleware,
        store=store,
        rate_limiter=EmbedRateLimiter(time_fn=clock),
    )
    app.include_router(routes_embed.router)
    return TestClient(app), created, store


def _headers(origin: str = "https://example.com") -> dict[str, str]:
    return {"Origin": origin}


def test_embed_session_returns_scoped_context(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="gateway.embed")
    client, created, _store = _client(tmp_path)

    resp = client.post(
        f"/api/embed/session?api_key={created.secret}",
        headers=_headers(),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == "tenant-a"
    assert body["key_id"] == created.record.key_id
    assert body["session_token"]
    assert created.secret not in caplog.text
    assert "tenant_id=tenant-a" in caplog.text


def test_embed_chat_proxies_to_existing_brain_chat(tmp_path, monkeypatch):
    client, created, _store = _client(tmp_path)
    proxy = AsyncMock(return_value=JSONResponse({"reply": "hi"}))
    monkeypatch.setattr(routes_embed, "_proxy_to_brain", proxy)

    resp = client.post(
        "/api/embed/chat",
        headers={
            "Authorization": f"Bearer {created.secret}",
            "Origin": "https://example.com",
        },
        json={"message": "hello"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"reply": "hi"}
    assert proxy.await_args.args[1] == "chat"


def test_embed_tts_uses_tts_service(tmp_path, monkeypatch):
    client, created, _store = _client(tmp_path)
    result = SimpleNamespace(
        audio_bytes=b"RIFF",
        content_type="audio/wav",
        provider="edge-tts",
        route_kind="provider",
        route_target="edge-tts",
        sample_rate=24000,
        latency_ms=1.2,
    )
    fake_service = SimpleNamespace(
        synthesize=lambda request, provider="": SimpleNamespace(
            result=result,
            fallback=False,
            fallback_reason="",
        )
    )
    monkeypatch.setattr(routes_embed, "_get_service", lambda: fake_service)

    resp = client.post(
        "/api/embed/tts",
        headers={
            "Authorization": f"Bearer {created.secret}",
            "Origin": "https://example.com",
        },
        json={"text": "hello"},
    )

    assert resp.status_code == 200
    assert resp.content == b"RIFF"
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.headers["X-TTS-Provider"] == "edge-tts"


def test_embed_asr_uses_audio_transcriber(tmp_path, monkeypatch):
    client, created, _store = _client(tmp_path)
    transcribe = AsyncMock(
        return_value=IngestionResult(
            content_type="audio_transcription",
            content="hello",
        )
    )
    monkeypatch.setattr(routes_embed, "transcribe", transcribe)

    resp = client.post(
        "/api/embed/asr",
        headers={
            "Authorization": f"Bearer {created.secret}",
            "Origin": "https://example.com",
        },
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )

    assert resp.status_code == 200
    assert resp.json()["text"] == "hello"
    assert transcribe.await_count == 1


def test_embed_websocket_closes_invalid_key_with_4401(tmp_path):
    client, _created, _store = _client(tmp_path)

    with client.websocket_connect("/ws/embed/client-a?api_key=bad") as websocket:
        with pytest.raises(WebSocketDisconnect) as exc:
            websocket.receive_json()

    assert exc.value.code == 4401


def test_embed_websocket_reuses_existing_websocket_endpoint(tmp_path, monkeypatch):
    client, created, _store = _client(tmp_path)

    async def fake_websocket_endpoint(websocket: WebSocket, client_id: str):
        await websocket.accept()
        auth = websocket.scope["state"]["embed_auth"]
        await websocket.send_json(
            {
                "client_id": client_id,
                "tenant_id": auth.tenant_id,
                "key_id": auth.key_id,
            }
        )
        await websocket.close()

    monkeypatch.setattr(routes_embed.websocket_routes, "websocket_endpoint", fake_websocket_endpoint)

    with client.websocket_connect(
        f"/ws/embed/client-a?api_key={created.secret}",
        headers=_headers(),
    ) as websocket:
        payload = websocket.receive_json()

    assert payload == {
        "client_id": "client-a",
        "tenant_id": "tenant-a",
        "key_id": created.record.key_id,
    }


def test_valid_key_runs_chat_tts_and_websocket_flow(tmp_path, monkeypatch):
    client, created, _store = _client(tmp_path)
    proxy = AsyncMock(return_value=JSONResponse({"reply": "hi"}))
    monkeypatch.setattr(routes_embed, "_proxy_to_brain", proxy)
    result = SimpleNamespace(
        audio_bytes=b"RIFF",
        content_type="audio/wav",
        provider="edge-tts",
        route_kind="provider",
        route_target="edge-tts",
        sample_rate=24000,
        latency_ms=1.2,
    )
    monkeypatch.setattr(
        routes_embed,
        "_get_service",
        lambda: SimpleNamespace(
            synthesize=lambda request, provider="": SimpleNamespace(
                result=result,
                fallback=False,
                fallback_reason="",
            )
        ),
    )

    async def fake_websocket_endpoint(websocket: WebSocket, client_id: str):
        await websocket.accept()
        await websocket.send_json({"event": "server_init_ack", "client_id": client_id})
        await websocket.close()

    monkeypatch.setattr(routes_embed.websocket_routes, "websocket_endpoint", fake_websocket_endpoint)
    headers = {
        "Authorization": f"Bearer {created.secret}",
        "Origin": "https://example.com",
    }

    chat_resp = client.post("/api/embed/chat", headers=headers, json={"message": "hello"})
    tts_resp = client.post("/api/embed/tts", headers=headers, json={"text": "hello"})
    with client.websocket_connect(
        f"/ws/embed/client-flow?api_key={created.secret}",
        headers=_headers(),
    ) as websocket:
        ws_frame = websocket.receive_json()

    assert chat_resp.status_code == 200
    assert chat_resp.json() == {"reply": "hi"}
    assert tts_resp.status_code == 200
    assert tts_resp.content == b"RIFF"
    assert ws_frame == {"event": "server_init_ack", "client_id": "client-flow"}

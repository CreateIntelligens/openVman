"""Streaming ASR relay: auth, frame forwarding and transcript relay."""

from __future__ import annotations

import asyncio
import json
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway import asr_stream


class FakeUpstream:
    def __init__(self):
        self.sent: list[dict] = []
        self._replies = [
            json.dumps({"setupComplete": {}}),
            json.dumps({"serverContent": {"interimInputTranscription": {"text": "你好"}}}),
            json.dumps({"serverContent": {"inputTranscription": {"text": " 你好，急診在哪裡？ "}}}),
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        return self._replies.pop(0)

    def __aiter__(self):
        return self

    async def __anext__(self):
        # 跟真的 Gemini 一樣：收到音訊才有轉錄，回完之後連線保持開著。
        while not any("realtimeInput" in message for message in self.sent):
            await asyncio.sleep(0.01)
        if not self._replies:
            await asyncio.Event().wait()
        return self._replies.pop(0)


def _client(monkeypatch, *, allowed=True, embed=False):
    account = types.SimpleNamespace(
        user=types.SimpleNamespace(id="u1"), embed_key=object() if embed else None,
    )
    monkeypatch.setattr(asr_stream, "authenticate_websocket", lambda ws, runtime: account)
    monkeypatch.setattr(asr_stream, "get_auth_runtime", lambda: None)
    monkeypatch.setattr(
        asr_stream, "permitted_asr_preference",
        lambda runtime, user, stored: stored if allowed else "",
    )
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    usage: list[dict] = []
    monkeypatch.setattr(asr_stream, "record_usage_event", lambda **kw: usage.append(kw))
    monkeypatch.setattr(asr_stream, "usage_scope_for", lambda *a, **kw: {})
    app = FastAPI()
    app.include_router(asr_stream.router)
    return TestClient(app), usage


@pytest.mark.parametrize(("allowed", "embed"), [(False, False), (True, True)])
def test_unauthorized_callers_get_an_error(monkeypatch, allowed, embed):
    client, _ = _client(monkeypatch, allowed=allowed, embed=embed)
    with client.websocket_connect("/api/v1/asr/stream") as ws:
        assert ws.receive_json() == {"type": "error", "code": "not_allowed"}


def test_relays_audio_and_transcripts(monkeypatch):
    client, usage = _client(monkeypatch)
    upstream = FakeUpstream()
    monkeypatch.setattr(asr_stream.websockets, "connect", lambda *a, **kw: upstream)

    with client.websocket_connect("/api/v1/asr/stream") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_bytes(b"\x01\x00" * 1600)
        assert ws.receive_json() == {"type": "interim", "text": "你好"}
        assert ws.receive_json() == {"type": "final", "text": "你好，急診在哪裡？"}

    setup = upstream.sent[0]["setup"]
    assert setup["model"] == "models/gemini-3.5-transcribe-live"
    assert "zh-TW" in setup["inputAudioTranscription"]["languageCodes"]
    assert upstream.sent[1]["realtimeInput"]["audio"]["mimeType"] == "audio/pcm;rate=16000"
    assert usage and usage[0]["kind"] == "asr" and usage[0]["units"] == pytest.approx(0.1)

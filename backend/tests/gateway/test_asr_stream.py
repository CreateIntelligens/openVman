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


def tmp_log(monkeypatch):
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp()) / "asr_final_judge.jsonl"


def _client(monkeypatch, *, allowed=True, embed=False, judge=None):
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
    monkeypatch.setenv("ASR_FINAL_JUDGE_LOG", str(tmp_log(monkeypatch)))
    usage: list[dict] = []
    monkeypatch.setattr(asr_stream, "record_usage_event", lambda **kw: usage.append(kw))
    monkeypatch.setattr(asr_stream, "usage_scope_for", lambda *a, **kw: {})
    judged: list[tuple] = []

    async def fake_judge(project_id, interim, final):
        judged.append((project_id, interim, final))
        return judge(interim, final) if judge else final

    monkeypatch.setattr(asr_stream, "_judge_final", fake_judge)
    app = FastAPI()
    app.include_router(asr_stream.router)
    client = TestClient(app)
    client.judged = judged
    return client, usage


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



class ScriptedUpstream(FakeUpstream):
    def __init__(self, replies):
        super().__init__()
        self._replies = [json.dumps({"setupComplete": {}})] + [
            json.dumps({"serverContent": reply}) for reply in replies
        ]


def test_a_garbled_final_is_replaced_by_the_judged_interim(monkeypatch):
    # 實際回報（2026-09-29）：講 who am i，暫定字幕對，定稿送出 OMI。
    client, _ = _client(monkeypatch, judge=lambda interim, final: interim)
    upstream = ScriptedUpstream([
        {"interimInputTranscription": {"text": "who am i"}},
        {"inputTranscription": {"text": "OMI"}},
        {"interimInputTranscription": {"text": "hello"}},
        {"inputTranscription": {"text": "hello"}},
    ])
    monkeypatch.setattr(asr_stream.websockets, "connect", lambda *a, **kw: upstream)

    with client.websocket_connect("/api/v1/asr/stream?project_id=proj-x") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_bytes(b"\x01\x00" * 1600)
        assert ws.receive_json() == {"type": "interim", "text": "who am i"}
        assert ws.receive_json() == {"type": "final", "text": "who am i"}
        assert ws.receive_json() == {"type": "interim", "text": "hello"}
        assert ws.receive_json() == {"type": "final", "text": "hello"}

    # 定稿跟暫定字幕一樣時不問；只問了 OMI 那一句。
    assert client.judged == [("proj-x", "who am i", "OMI")]


@pytest.mark.parametrize(
    ("routes", "codes"),
    [
        (["zh", "en", "es"], ["zh-TW", "en-US", "es-ES"]),
        (["ko", "zh"], ["ko-KR", "zh-TW"]),
        (["nan"], ["zh-TW", "en-US", "es-ES"]),
    ],
)
def test_language_hints_follow_the_project_routes(monkeypatch, routes, codes):
    client, _ = _client(monkeypatch)
    seen = {}

    async def fake_routes(current, project_id, requested):
        seen["args"] = (project_id, requested)
        return routes

    monkeypatch.setattr(asr_stream.language_routes_mod, "effective_routes", fake_routes)
    upstream = FakeUpstream()
    monkeypatch.setattr(asr_stream.websockets, "connect", lambda *a, **kw: upstream)

    with client.websocket_connect("/api/v1/asr/stream?project_id=p1&language_routes=zh,en") as ws:
        assert ws.receive_json() == {"type": "ready"}

    assert upstream.sent[0]["setup"]["inputAudioTranscription"]["languageCodes"] == codes
    assert seen["args"] == ("p1", ["zh", "en"])


def test_judge_failure_keeps_the_final_and_logs_it(monkeypatch, tmp_path):
    log = tmp_path / "judge.jsonl"
    monkeypatch.setenv("ASR_FINAL_JUDGE_LOG", str(log))

    class Down:
        async def post(self, *a, **kw):
            raise ConnectionError("brain down")

    monkeypatch.setattr(asr_stream._http, "get", lambda: Down())
    text = asyncio.run(asr_stream._judge_final("p", "who am i", "OMI"))

    assert text == "OMI"
    record = json.loads(log.read_text(encoding="utf-8"))
    assert record["interim"] == "who am i" and record["final"] == "OMI"
    assert record["chosen"] == "final" and record["reason"].startswith("error:")

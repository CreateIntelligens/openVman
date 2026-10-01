"""R2T2 streaming protocol, permission isolation, and relay lifecycle."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.auth.models import AccountRole, ResourceType
from app.gateway import asr_stream


class ClientSocket:
    def __init__(self, frames=()):
        self.frames = list(frames)
        self.query_params = {"project_id": "project-test"}
        self.sent = []
        self.closed = False

    async def accept(self):
        pass

    async def close(self, **kwargs):
        self.closed = True

    async def send_json(self, message):
        self.sent.append(message)

    async def receive(self):
        if self.frames:
            return self.frames.pop(0)
        await asyncio.Event().wait()


class Upstream:
    def __init__(self, replies=(), *, handshake="connected", failure=None):
        self.sent = []
        self.replies = list(replies)
        self.handshake = handshake
        self.failure = failure
        self.ended = asyncio.Event()
        self.receiver_started = asyncio.Event()
        self.receiver_active = False
        self.receiver_cleaned = False
        self.closed = False

    async def __aenter__(self):
        if self.failure:
            raise self.failure
        return self

    async def __aexit__(self, *exc):
        assert not self.receiver_active
        self.closed = True

    async def recv(self):
        return json.dumps({"status": self.handshake})

    async def send(self, message):
        self.sent.append(message)
        if message == "YOUDAO_ONETIME_ASR_STREAM_EOS":
            self.ended.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.receiver_started.set()
        self.receiver_active = True
        try:
            await self.ended.wait()
            if self.replies:
                return json.dumps(self.replies.pop(0))
            raise StopAsyncIteration
        finally:
            self.receiver_active = False
            self.receiver_cleaned = True


def _reply(**body):
    return {"status": "success", "msg": body}


def _environment(monkeypatch, *, stored="r2t2-live", grants=None, embed=False):
    account = SimpleNamespace(
        user=SimpleNamespace(id="stream-test", role=AccountRole.ADMIN),
        embed_key=object() if embed else None,
    )
    state = {
        "stored": stored,
        "grants": list(grants if grants is not None else ["r2t2-live"]),
    }
    runtime = SimpleNamespace(account_access=SimpleNamespace(
        get_asr_provider=lambda _: state["stored"],
        list_grants=lambda _: [
            SimpleNamespace(resource_type=ResourceType.ASR_ENGINE, resource_id=id)
            for id in state["grants"]
        ],
    ))
    cfg = SimpleNamespace(
        asr_r2t2_stream_url="ws://10.9.0.37:8803/asr_stream_api_v1",
        asr_r2t2_secret_key="fixture-secret",
    )
    usage = []
    prompts = []

    async def glossary(current, project_id):
        prompts.append((current, project_id))
        return "鶴記，億發泵浦"

    async def routes(*args):
        return ["zh"]

    async def judge(*args):
        pytest.fail("R2T2 finals must not invoke Gemini's final judge")

    monkeypatch.setattr(asr_stream, "authenticate_websocket", lambda *a: account)
    monkeypatch.setattr(asr_stream, "get_auth_runtime", lambda: runtime)
    monkeypatch.setattr(asr_stream, "get_tts_config", lambda: cfg)
    monkeypatch.setattr(asr_stream, "project_asr_prompt", glossary)
    monkeypatch.setattr(asr_stream, "_project_routes", routes)
    monkeypatch.setattr(asr_stream, "_judge_final", judge)
    monkeypatch.setattr(asr_stream, "record_usage_event", lambda **kw: usage.append(kw))
    monkeypatch.setattr(asr_stream, "usage_scope_for", lambda *a, **kw: {})
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return account, state, cfg, usage, prompts


def _run(socket):
    asyncio.run(asyncio.wait_for(asr_stream.asr_stream(socket), timeout=2))


def test_rechunks_audio_flushes_padding_and_records_only_source_audio(monkeypatch):
    account, _, _, usage, prompts = _environment(monkeypatch)
    upstream = Upstream([_reply(reset=True, final_text="结束")])
    connected = []

    def connect(url, **kwargs):
        connected.append(url)
        return upstream

    monkeypatch.setattr(asr_stream.websockets, "connect", connect)
    audio = bytes(range(256)) * 25
    socket = ClientSocket([
        {"bytes": audio[:3200]}, {"bytes": audio[3200:]},
        {"text": '{"type":"end"}'},
    ])
    _run(socket)
    binary = [frame for frame in upstream.sent if isinstance(frame, bytes)]
    assert [len(frame) for frame in binary] == [5120, 5120]
    assert binary[0] == audio[:5120]
    assert binary[1] == audio[5120:] + b"\0" * 3840
    assert upstream.sent[-1] == "YOUDAO_ONETIME_ASR_STREAM_EOS"
    assert socket.sent == [{"type": "ready"}, {"type": "final", "text": "結束"}]
    assert upstream.closed
    assert connected == ["ws://10.9.0.37:8803/asr_stream_api_v1"]
    handshake = json.loads(upstream.sent[0])
    assert handshake["language"] == "Chinese"
    assert handshake["use_vad"] is True
    assert handshake["secret_key"] == "fixture-secret"
    assert handshake["system_prompt"] == "鶴記，億發泵浦"
    assert handshake["requestId"]
    assert prompts == [(account, "project-test")]
    assert len(usage) == 1
    assert usage[0]["provider"] == "r2t2-live"
    assert usage[0]["units"] == pytest.approx(0.2)


def test_incremental_transcripts_reset_and_final_text_override(monkeypatch):
    _environment(monkeypatch)
    upstream = Upstream([
        _reply(text="好，泵"), _reply(text="浦在哪里"),
        _reply(text="", reset=False),
        _reply(text="？", reset=True, final_text="泵浦在哪里？"),
        _reply(text="设备"), _reply(text="开关", reset=True),
    ])
    monkeypatch.setattr(asr_stream.websockets, "connect", lambda *a, **kw: upstream)
    socket = ClientSocket([{"text": '{"type":"end"}'}])
    _run(socket)
    assert socket.sent == [
        {"type": "ready"},
        {"type": "interim", "text": "好，泵"},
        {"type": "interim", "text": "好，泵浦在哪裏"},
        {"type": "final", "text": "泵浦在哪裏？"},
        {"type": "interim", "text": "設備"},
        {"type": "final", "text": "設備開關"},
    ]


@pytest.mark.parametrize("failure", ["connection", "handshake", "transcript"])
def test_upstream_failures_report_fallback_error(monkeypatch, failure):
    _environment(monkeypatch)
    upstream = Upstream(
        [{"status": "error"}] if failure == "transcript" else [],
        handshake="error" if failure == "handshake" else "connected",
        failure=ConnectionError("unreachable") if failure == "connection" else None,
    )
    monkeypatch.setattr(asr_stream.websockets, "connect", lambda *a, **kw: upstream)
    socket = ClientSocket([{"text": '{"type":"end"}'}])
    _run(socket)
    assert socket.sent[-1] == {"type": "error", "code": "upstream_failed"}
    assert socket.closed


@pytest.mark.parametrize("missing", ["asr_r2t2_stream_url", "asr_r2t2_secret_key"])
def test_missing_configuration_is_reported_without_upstream_connection(monkeypatch, missing):
    _, _, cfg, _, _ = _environment(monkeypatch)
    setattr(cfg, missing, "")
    monkeypatch.setattr(
        asr_stream.websockets, "connect",
        lambda *a, **kw: pytest.fail("unconfigured engine connected"),
    )
    socket = ClientSocket()
    _run(socket)
    assert socket.sent == [{"type": "error", "code": "not_configured"}]


@pytest.mark.parametrize(
    ("stored", "grants", "embed"),
    [
        ("r2t2-live", ["r2t2"], False),
        ("r2t2", ["r2t2", "r2t2-live"], False),
        ("r2t2-live", [], False),
        ("r2t2-live", ["r2t2-live"], True),
    ],
)
def test_batch_grants_and_embed_callers_cannot_use_streaming(
    monkeypatch, stored, grants, embed,
):
    _environment(monkeypatch, stored=stored, grants=grants, embed=embed)
    socket = ClientSocket()
    _run(socket)
    assert socket.sent == [{"type": "error", "code": "not_allowed"}]


def test_selection_and_revocation_are_resolved_from_current_grants(monkeypatch):
    account, state, _, _, _ = _environment(
        monkeypatch, grants=["r2t2-live", "gemini-live"],
    )
    assert asr_stream._allowed(account) == "r2t2-live"
    state["stored"] = "gemini-live"
    assert asr_stream._allowed(account) == "gemini-live"
    state["grants"].remove("gemini-live")
    assert asr_stream._allowed(account) == ""


def test_client_disconnect_cancels_receiver_before_closing_upstream(monkeypatch):
    _environment(monkeypatch)
    upstream = Upstream()
    monkeypatch.setattr(asr_stream.websockets, "connect", lambda *a, **kw: upstream)

    class DisconnectingClient(ClientSocket):
        async def receive(self):
            await upstream.receiver_started.wait()
            return {"type": "websocket.disconnect"}

    socket = DisconnectingClient()
    _run(socket)
    assert upstream.receiver_cleaned
    assert upstream.closed
    assert socket.sent == [{"type": "ready"}]


def test_premature_upstream_close_reports_error_and_cancels_client_receiver(monkeypatch):
    _environment(monkeypatch)

    class ClosedUpstream(Upstream):
        async def __anext__(self):
            raise StopAsyncIteration

    class WaitingClient(ClientSocket):
        cleaned = False

        async def receive(self):
            try:
                await asyncio.Event().wait()
            finally:
                self.cleaned = True

    upstream = ClosedUpstream()
    monkeypatch.setattr(asr_stream.websockets, "connect", lambda *a, **kw: upstream)
    socket = WaitingClient()
    _run(socket)
    assert socket.cleaned
    assert upstream.closed
    assert socket.sent == [
        {"type": "ready"}, {"type": "error", "code": "upstream_failed"},
    ]

"""gemini-live-batch: whole clip through a fresh Gemini Live session, explicit-only."""

from __future__ import annotations

import asyncio
import json
import types

import httpx
import pytest
import websockets
from fastapi import HTTPException

from app.auth.settings_repository import SERVER_ASR_PROVIDERS, TAIWANESE_ASR_PROVIDERS
from app.gateway import gemini_live_batch, ingestion_audio
from app.system_resources import ASR_ENGINE_LABELS
from app.upstream_guard import ASR_BREAKER, clear_recent_attempts, recent_attempts

KEY = "test-gemini-key"
ENGINE = "gemini-live-batch"
CREDENTIAL = types.SimpleNamespace(
    api_key=KEY, source="shared", credential_id="gemini", configured=True,
)
PCM = b"\x01\x00" * 3200  # 0.2 s


def _final(text):
    return {"serverContent": {"inputTranscription": {"text": text}}}


_DONE = {"serverContent": {"generationComplete": True}}


def _activity(kind):
    return {"serverContent": {}, "voiceActivity": {"type": kind}}


class FakeLive:
    """Scripted Live session: setupComplete, then the replies, then silence or a close."""

    def __init__(self, replies=(), *, forever=None, close_code=None):
        self.sent: list[dict] = []
        self.closed = False
        self.headers = None
        self._replies = [json.dumps(reply) for reply in replies]
        self._forever = json.dumps(forever) if forever else None
        self._close_code = close_code
        self._setup_done = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True
        return False

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        if not self._setup_done:
            self._setup_done = True
            return json.dumps({"setupComplete": {}})
        if self._replies:
            return self._replies.pop(0)
        if self._close_code:
            close = websockets.frames.Close(self._close_code, "boom")
            raise websockets.ConnectionClosedError(close, None)
        if self._forever:
            await asyncio.sleep(0.01)
            return self._forever
        await asyncio.Event().wait()


def _connect(monkeypatch, upstream: FakeLive) -> dict:
    seen: dict = {}

    def connect(url, **kwargs):
        seen.update(url=url, **kwargs)
        return upstream

    monkeypatch.setattr(gemini_live_batch.websockets, "connect", connect)
    return seen


async def _send(upstream: FakeLive, transcription=None):
    return await gemini_live_batch.transcribe_pcm(
        PCM, api_key=KEY,
        transcription=transcription or {"languageCodes": ["en-US"]},
        connect_timeout=2,
    )


@pytest.fixture(autouse=True)
def _clean_guard():
    ASR_BREAKER.reset()
    ingestion_audio._unreachable_until.clear()
    clear_recent_attempts()
    yield
    ASR_BREAKER.reset()
    ingestion_audio._unreachable_until.clear()


@pytest.mark.asyncio
async def test_frames_clip_with_manual_activity_and_stops_on_generation_complete(monkeypatch):
    # generationComplete 之後還有 ACTIVITY_END：不必等它。
    upstream = FakeLive([
        _activity("ACTIVITY_START"), _final(" What is PRP? "), _DONE, _activity("ACTIVITY_END"),
    ])
    seen = _connect(monkeypatch, upstream)

    result = await _send(upstream)

    assert (result.text, result.finals) == ("What is PRP?", ("What is PRP?",))
    assert result.completed_by == "generation_complete"
    assert seen["additional_headers"] == {"x-goog-api-key": KEY}
    assert seen["open_timeout"] == 2
    setup = upstream.sent[0]["setup"]
    assert setup["realtimeInputConfig"] == {"automaticActivityDetection": {"disabled": True}}
    assert setup["inputAudioTranscription"] == {"languageCodes": ["en-US"]}
    assert upstream.sent[1] == {"realtimeInput": {"activityStart": {}}}
    assert upstream.sent[-1] == {"realtimeInput": {"activityEnd": {}}}
    assert not any("audioStreamEnd" in message["realtimeInput"] for message in upstream.sent[1:])
    assert upstream.closed


@pytest.mark.asyncio
async def test_pads_lead_silence_only(monkeypatch):
    import base64

    upstream = FakeLive([_final("hi"), _DONE])
    _connect(monkeypatch, upstream)

    await _send(upstream)

    audio = b"".join(
        base64.b64decode(message["realtimeInput"]["audio"]["data"])
        for message in upstream.sent if "audio" in message.get("realtimeInput", {})
    )
    lead = int(16000 * 0.3) * 2
    assert audio == b"\0" * lead + PCM


@pytest.mark.asyncio
async def test_joins_every_final_before_completion(monkeypatch):
    upstream = FakeLive([_final("I lost my card."), _final("Can I register?"), _DONE])
    _connect(monkeypatch, upstream)
    assert (await _send(upstream)).text == "I lost my card. Can I register?"


@pytest.mark.asyncio
async def test_chinese_finals_join_without_a_space(monkeypatch):
    upstream = FakeLive([_final("你好"), _final("請問"), _DONE])
    _connect(monkeypatch, upstream)
    assert (await _send(upstream)).text == "你好請問"


@pytest.mark.asyncio
async def test_silence_ends_on_activity_end_with_empty_text(monkeypatch):
    monkeypatch.setattr(gemini_live_batch, "_SETTLE_SECONDS", 0.01)
    upstream = FakeLive([_activity("ACTIVITY_START"), _activity("ACTIVITY_END")])
    _connect(monkeypatch, upstream)

    result = await _send(upstream)

    assert (result.text, result.finals, result.completed_by) == ("", (), "activity_end")
    assert upstream.closed


@pytest.mark.asyncio
async def test_final_arriving_right_after_activity_end_is_kept(monkeypatch):
    upstream = FakeLive([_activity("ACTIVITY_END"), _final("late"), _DONE])
    _connect(monkeypatch, upstream)
    assert (await _send(upstream)).text == "late"


@pytest.mark.asyncio
async def test_server_side_close_counts_as_5xx(monkeypatch):
    upstream = FakeLive(close_code=1011)
    _connect(monkeypatch, upstream)
    with pytest.raises(gemini_live_batch.GeminiLiveBatchError) as caught:
        await _send(upstream)
    assert caught.value.status_code == 503
    assert KEY not in str(caught.value)


@pytest.mark.asyncio
async def test_policy_close_is_not_a_server_failure(monkeypatch):
    upstream = FakeLive(close_code=1008)
    _connect(monkeypatch, upstream)
    with pytest.raises(gemini_live_batch.GeminiLiveBatchError) as caught:
        await _send(upstream)
    assert caught.value.status_code == 0


@pytest.mark.asyncio
async def test_rejected_setup_raises(monkeypatch):
    upstream = FakeLive()
    upstream._setup_done = True
    upstream._replies = [json.dumps({"error": "nope"})]
    _connect(monkeypatch, upstream)
    with pytest.raises(gemini_live_batch.GeminiLiveBatchError):
        await _send(upstream)


@pytest.mark.asyncio
async def test_unreachable_is_a_connection_error(monkeypatch):
    def refuse(*args, **kwargs):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(gemini_live_batch.websockets, "connect", refuse)
    with pytest.raises(httpx.ConnectError):
        await _send(FakeLive())


@pytest.mark.asyncio
async def test_connect_timeout_is_classified_as_connect(monkeypatch):
    def slow(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(gemini_live_batch.websockets, "connect", slow)
    with pytest.raises(httpx.ConnectTimeout):
        await _send(FakeLive())


# --- _transcribe_gemini_live_batch --------------------------------------------------


@pytest.fixture
def no_ffmpeg(monkeypatch):
    monkeypatch.setattr(ingestion_audio, "_decode_pcm16", lambda path: PCM)


@pytest.mark.asyncio
async def test_project_routes_and_vocabulary_reach_the_session(monkeypatch, no_ffmpeg):
    seen = []

    def resolve(project_id, runtime=None):
        seen.append(project_id)
        return CREDENTIAL

    async def vocabulary():
        return ["PRP", "DIVA PRO"]

    monkeypatch.setattr(ingestion_audio, "resolve_gemini_credential", resolve)
    upstream = FakeLive([_final("ok"), _DONE])
    _connect(monkeypatch, upstream)

    text = await ingestion_audio._transcribe_gemini_live_batch(
        "clip.webm", "t", prompt="ignored by Live",
        routes=["en"], project_id="proj-1", vocabulary_loader=vocabulary,
    )

    assert text == "ok"
    assert seen == ["proj-1"]
    assert upstream.sent[0]["setup"]["inputAudioTranscription"] == {
        "languageCodes": ["en-US"], "customVocabulary": ["PRP", "DIVA PRO"],
    }


@pytest.mark.asyncio
async def test_no_project_uses_the_deployment_credential(monkeypatch, no_ffmpeg):
    seen = []
    monkeypatch.setattr(
        ingestion_audio, "resolve_gemini_credential",
        lambda project_id, runtime=None: seen.append(project_id) or CREDENTIAL,
    )
    _connect(monkeypatch, FakeLive([_final("ok"), _DONE]))
    await ingestion_audio._transcribe_gemini_live_batch("clip.wav", "t")
    assert seen == [None]


# --- transcribe(): budget, breaker, attempt log, chain ---------------------------------


def _cfg(**overrides):
    fields = {
        "asr_provider": "breeze", "asr_breeze_url": "http://breeze", "asr_r2t2_url": "",
        "asr_r2t2_dev_url": "", "asr_sensevoice_url": "", "whisper_api_key": "",
        "asr_node_base_seconds": 8.0, "asr_node_per_audio_second": 0.5,
    }
    fields.update(overrides)
    return types.SimpleNamespace(**fields)


def _use(monkeypatch, *, ready=True, cfg=None):
    cfg = cfg or _cfg()
    monkeypatch.setattr(ingestion_audio, "get_tts_config", lambda: cfg)
    monkeypatch.setattr(
        ingestion_audio, "_gemini_ready", lambda project_id: ready,
    )
    monkeypatch.setattr(
        ingestion_audio, "resolve_gemini_credential",
        lambda project_id, runtime=None: CREDENTIAL,
    )
    return cfg


def test_selectable_but_not_for_taiwanese():
    assert ENGINE in SERVER_ASR_PROVIDERS
    assert ENGINE in ASR_ENGINE_LABELS
    assert ENGINE not in TAIWANESE_ASR_PROVIDERS


def test_not_in_default_chain(monkeypatch):
    cfg = _use(monkeypatch)
    assert ingestion_audio._resolve_chain(cfg) == ["breeze"]


def test_not_a_fallback_for_another_preference(monkeypatch):
    cfg = _use(monkeypatch, cfg=_cfg(asr_sensevoice_url="http://sv"))
    assert ENGINE not in ingestion_audio._resolve_chain(cfg, "sensevoice")


def test_project_order_alone_does_not_pull_it_in(monkeypatch):
    # 跟 r2t2-dev 一樣：順位表裡有也要被選中才跑，順位只決定被選中之後的備援。
    cfg = _use(monkeypatch)
    assert ingestion_audio._resolve_chain(cfg, order=(ENGINE, "breeze")) == ["breeze"]


def test_explicit_choice_runs_it_first(monkeypatch):
    cfg = _use(monkeypatch)
    assert ingestion_audio._resolve_chain(cfg, ENGINE) == [ENGINE, "breeze"]


def test_unresolvable_credential_leaves_it_out(monkeypatch):
    cfg = _use(monkeypatch, ready=False)
    assert ingestion_audio._resolve_chain(cfg, ENGINE) == ["breeze"]


def test_readiness_asks_for_this_projects_credential(monkeypatch):
    seen = []
    monkeypatch.setattr(
        ingestion_audio, "resolve_gemini_credential",
        lambda project_id, runtime=None: seen.append(project_id) or CREDENTIAL,
    )
    assert ingestion_audio._provider_ready(_cfg(), ENGINE, "proj-1") is True
    assert seen == ["proj-1"]


def test_broken_project_credential_is_not_ready(monkeypatch):
    def broken(project_id, runtime=None):
        raise HTTPException(status_code=503, detail="project_gemini_credential_unavailable")

    monkeypatch.setattr(ingestion_audio, "resolve_gemini_credential", broken)
    assert ingestion_audio._provider_ready(_cfg(), ENGINE, "proj-1") is False


def test_configured_providers_lists_it_per_project(monkeypatch):
    cfg = _cfg()
    monkeypatch.setattr(ingestion_audio, "get_tts_config", lambda: cfg)
    monkeypatch.setattr(ingestion_audio, "_gemini_ready", lambda project_id: project_id == "with-key")
    assert ENGINE in ingestion_audio.configured_providers("with-key")
    assert ENGINE not in ingestion_audio.configured_providers("no-key")


@pytest.mark.asyncio
async def test_transcribe_explicit_success_logs_an_attempt(monkeypatch, no_ffmpeg):
    _use(monkeypatch)
    _connect(monkeypatch, FakeLive([_final("Where is the restroom?"), _DONE]))

    result = await ingestion_audio.transcribe(
        "clip.wav", "t", ENGINE, routes=["en"], allowed_providers={ENGINE},
        audio_seconds=2.0, project_id="proj-1",
    )

    assert (result.provider, result.content) == (ENGINE, "Where is the restroom?")
    attempt = recent_attempts()[-1]
    assert attempt["node"] == ENGINE
    assert attempt["outcome"] == "ok"
    assert attempt["host"] == "generativelanguage.googleapis.com"
    assert attempt["budget_ms"] == 9000


@pytest.mark.asyncio
async def test_endless_interims_hit_the_node_budget_and_close(monkeypatch, no_ffmpeg):
    _use(monkeypatch, cfg=_cfg(asr_node_base_seconds=0.05, asr_node_per_audio_second=0))
    upstream = FakeLive(forever={"serverContent": {"interimInputTranscription": {"text": "uh"}}})
    _connect(monkeypatch, upstream)

    result = await ingestion_audio.transcribe(
        "clip.wav", "t", ENGINE, allowed_providers={ENGINE}, audio_seconds=1.0,
    )

    assert result.provider is None or result.provider == ""
    assert result.content == "（音訊轉錄失敗）"
    assert upstream.closed
    attempt = recent_attempts()[-1]
    assert attempt["outcome"] == "timeout_total"
    assert attempt["node"] == ENGINE


@pytest.mark.asyncio
async def test_no_reply_at_all_is_a_timeout_not_silence(monkeypatch, no_ffmpeg):
    # 靜音會回 ACTIVITY_END；什麼都不回是上游故障，不能當成空字串交差。
    _use(monkeypatch, cfg=_cfg(asr_node_base_seconds=0.05, asr_node_per_audio_second=0))
    upstream = FakeLive()
    _connect(monkeypatch, upstream)

    result = await ingestion_audio.transcribe(
        "clip.wav", "t", ENGINE, allowed_providers={ENGINE}, audio_seconds=1.0,
    )

    assert result.content == "（音訊轉錄失敗）"
    assert recent_attempts()[-1]["outcome"] == "timeout_total"
    assert upstream.closed


@pytest.mark.asyncio
async def test_repeated_server_close_opens_the_breaker(monkeypatch, no_ffmpeg):
    _use(monkeypatch)
    for _ in range(2):
        _connect(monkeypatch, FakeLive(close_code=1011))
        await ingestion_audio.transcribe(
            "clip.wav", "t", ENGINE, allowed_providers={ENGINE}, audio_seconds=1.0,
        )
    assert ASR_BREAKER.cooling(ENGINE) > 0


@pytest.mark.asyncio
async def test_policy_close_does_not_open_the_breaker(monkeypatch, no_ffmpeg):
    _use(monkeypatch)
    for _ in range(3):
        _connect(monkeypatch, FakeLive(close_code=1008))
        await ingestion_audio.transcribe(
            "clip.wav", "t", ENGINE, allowed_providers={ENGINE}, audio_seconds=1.0,
        )
    assert ASR_BREAKER.cooling(ENGINE) == 0


@pytest.mark.asyncio
async def test_broken_project_key_does_not_trip_the_breaker_for_everyone(monkeypatch, no_ffmpeg):
    _use(monkeypatch)

    def broken(project_id, runtime=None):
        raise HTTPException(status_code=503, detail="project_gemini_credential_unavailable")

    monkeypatch.setattr(ingestion_audio, "resolve_gemini_credential", broken)
    for _ in range(3):
        await ingestion_audio.transcribe(
            "clip.wav", "t", ENGINE, allowed_providers={ENGINE}, audio_seconds=1.0,
            project_id="proj-1",
        )
    assert ASR_BREAKER.cooling(ENGINE) == 0
    assert recent_attempts()[-1]["outcome"] == "error"


@pytest.mark.asyncio
async def test_preferred_failure_falls_back_to_the_chain(monkeypatch, no_ffmpeg):
    _use(monkeypatch)
    _connect(monkeypatch, FakeLive(close_code=1011))

    async def breeze(file_path, trace_id, prompt=""):
        return "from breeze"

    monkeypatch.setitem(ingestion_audio._TRANSCRIBERS, "breeze", breeze)

    result = await ingestion_audio.transcribe("clip.wav", "t", ENGINE, audio_seconds=1.0)

    assert (result.provider, result.content) == ("breeze", "from breeze")


@pytest.mark.asyncio
async def test_dispatcher_passes_the_project_to_transcribe(monkeypatch):
    from app.gateway import dispatcher

    seen = {}

    async def fake(file_path, trace_id, provider, **kwargs):
        seen.update(provider=provider, **kwargs)
        return ingestion_audio.IngestionResult(
            content_type="audio_transcription", content="hi", provider=ENGINE,
        )

    monkeypatch.setattr(ingestion_audio, "transcribe", fake)
    await dispatcher._process("audio", "c.wav", "t", ENGINE, None, "proj-1")
    assert seen == {"provider": ENGINE, "project_id": "proj-1"}

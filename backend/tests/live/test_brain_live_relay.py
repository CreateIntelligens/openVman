import asyncio
import base64
import json

import pytest

from app.gateway.brain_live_relay import BrainLiveRelay
from app.providers.base import NormalizedTTSResult
from app.service import SynthesisOutput
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


@pytest.mark.asyncio
async def test_brain_live_relay_passthrough_when_voice_source_is_gemini():
    session = Session(client_id="client-1")
    emitted: list[dict[str, object]] = []

    class BrokenTTSService:
        def synthesize(self, request):  # pragma: no cover - test guard
            raise AssertionError("TTS should not run for gemini voice source")

    async def sink(payload: dict[str, object]) -> None:
        emitted.append(payload)

    relay = BrainLiveRelay(
        session,
        voice_source="gemini",
        tts_service=BrokenTTSService(),
        event_sink=sink,
    )
    payload = {
        "event": "server_stream_chunk",
        "chunk_id": "chunk-1",
        "text": "保留 Gemini 音訊",
        "audio_base64": "Z2VtaW5pLWF1ZGlv",
        "is_final": False,
    }
    relay._ws = FakeWebSocket(relay, [json.dumps(payload)])

    await relay._listen()

    assert emitted == [payload]


@pytest.mark.asyncio
async def test_brain_live_relay_replaces_gemini_audio_when_voice_source_is_custom():
    session = Session(client_id="client-2")
    emitted: list[dict[str, object]] = []
    emitted_event = asyncio.Event()

    class FakeTTSService:
        def __init__(self) -> None:
            self.requests: list[str] = []

        def synthesize(self, request):
            self.requests.append(request.text)
            return SynthesisOutput(
                result=NormalizedTTSResult(
                    audio_bytes=b"custom-audio",
                    content_type="audio/wav",
                    sample_rate=24000,
                    provider="indextts",
                    route_kind="provider",
                    route_target="indextts",
                    latency_ms=8.1,
                )
            )

    tts_service = FakeTTSService()

    async def sink(payload: dict[str, object]) -> None:
        emitted.append(payload)
        emitted_event.set()

    relay = BrainLiveRelay(
        session,
        voice_source="custom",
        tts_service=tts_service,
        event_sink=sink,
    )
    payload = {
        "event": "server_stream_chunk",
        "chunk_id": "chunk-2",
        "text": "改用自訂語音",
        "audio_base64": "b3JpZ2luYWwtZ2VtaW5pLWF1ZGlv",
        "is_final": True,
    }
    relay._ws = FakeWebSocket(relay, [json.dumps(payload)])

    await relay._listen()
    await asyncio.wait_for(emitted_event.wait(), timeout=1)
    await relay.close()

    assert tts_service.requests == ["改用自訂語音"]
    assert emitted == [
        {
            **payload,
            "audio_base64": base64.b64encode(b"custom-audio").decode("utf-8"),
        }
    ]


@pytest.mark.asyncio
async def test_brain_live_relay_emits_empty_audio_when_custom_tts_fails():
    session = Session(client_id="client-3")
    emitted: list[dict[str, object]] = []
    emitted_event = asyncio.Event()

    class BrokenTTSService:
        def synthesize(self, request):
            raise RuntimeError("tts boom")

    async def sink(payload: dict[str, object]) -> None:
        emitted.append(payload)
        emitted_event.set()

    relay = BrainLiveRelay(
        session,
        voice_source="custom",
        tts_service=BrokenTTSService(),
        event_sink=sink,
    )
    payload = {
        "event": "server_stream_chunk",
        "chunk_id": "chunk-3",
        "text": "只有文字",
        "audio_base64": "c2hvdWxkLWJlLWRyb3BwZWQ=",
        "is_final": True,
    }
    relay._ws = FakeWebSocket(relay, [json.dumps(payload)])

    await relay._listen()
    await asyncio.wait_for(emitted_event.wait(), timeout=1)
    await relay.close()

    assert emitted == [
        {
            **payload,
            "audio_base64": "",
        }
    ]

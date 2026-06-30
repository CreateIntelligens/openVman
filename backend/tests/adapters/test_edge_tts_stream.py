from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

import app.providers.edge_tts_adapter as edge_module
from app.config import TTSRouterConfig
from app.providers.base import SynthesizeRequest
from app.providers.edge_tts_adapter import EdgeTTSAdapter, EdgeTTSError


def _make_config(edge_enabled: bool = True) -> TTSRouterConfig:
    return TTSRouterConfig(edge_tts_enabled=edge_enabled)


class _FakeCommunicate:
    """Mimics edge_tts.Communicate, yielding a fixed chunk sequence."""

    def __init__(self, text: str, voice: str) -> None:
        self.text = text
        self.voice = voice

    async def stream(self) -> AsyncIterator[dict]:
        yield {"type": "WordBoundary", "offset": 0}
        yield {"type": "audio", "data": b"chunk-1"}
        yield {"type": "audio", "data": b"chunk-2"}


async def _collect(stream: AsyncIterator[bytes]) -> list[bytes]:
    return [chunk async for chunk in stream]


@pytest.mark.asyncio
async def test_synthesize_stream_yields_only_audio_chunks(monkeypatch):
    monkeypatch.setattr(edge_module.edge_tts, "Communicate", _FakeCommunicate, raising=False)
    adapter = EdgeTTSAdapter(_make_config())

    chunks = await _collect(
        adapter.synthesize_stream(SynthesizeRequest(text="你好"))
    )

    assert chunks == [b"chunk-1", b"chunk-2"]


@pytest.mark.asyncio
async def test_synthesize_stream_empty_text_raises(monkeypatch):
    monkeypatch.setattr(edge_module.edge_tts, "Communicate", _FakeCommunicate, raising=False)
    adapter = EdgeTTSAdapter(_make_config())

    with pytest.raises(EdgeTTSError):
        await _collect(adapter.synthesize_stream(SynthesizeRequest(text="   ")))


@pytest.mark.asyncio
async def test_synthesize_stream_falls_back_for_non_edge_voice(monkeypatch):
    """非 Edge 格式的 voice（如 IndexTTS 角色名 hayley）應回退到預設 voice。"""
    captured: dict[str, str] = {}

    class _CapturingCommunicate(_FakeCommunicate):
        def __init__(self, text: str, voice: str) -> None:
            super().__init__(text, voice)
            captured["voice"] = voice

    monkeypatch.setattr(edge_module.edge_tts, "Communicate", _CapturingCommunicate, raising=False)
    config = _make_config()
    adapter = EdgeTTSAdapter(config)

    await _collect(
        adapter.synthesize_stream(SynthesizeRequest(text="hi", voice_hint="hayley"))
    )

    assert captured["voice"] == config.edge_tts_voice
    assert captured["voice"] != "hayley"


@pytest.mark.asyncio
async def test_synthesize_stream_uses_voice_hint(monkeypatch):
    captured: dict[str, str] = {}

    class _CapturingCommunicate(_FakeCommunicate):
        def __init__(self, text: str, voice: str) -> None:
            super().__init__(text, voice)
            captured["voice"] = voice

    monkeypatch.setattr(edge_module.edge_tts, "Communicate", _CapturingCommunicate, raising=False)
    adapter = EdgeTTSAdapter(_make_config())

    await _collect(
        adapter.synthesize_stream(
            SynthesizeRequest(text="hi", voice_hint="zh-TW-HsiaoChenNeural")
        )
    )

    assert captured["voice"] == "zh-TW-HsiaoChenNeural"

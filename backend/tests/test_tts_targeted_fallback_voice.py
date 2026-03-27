from __future__ import annotations

from unittest.mock import MagicMock

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.service import TTSRouterService


def _make_config() -> TTSRouterConfig:
    return TTSRouterConfig(
        tts_index_url="http://index",
        tts_index_character="hayley",
        edge_tts_enabled=True,
        edge_tts_voice="zh-TW-HsiaoChenNeural",
    )


def _ok_result(provider: str) -> NormalizedTTSResult:
    return NormalizedTTSResult(
        audio_bytes=b"\x00\x01",
        content_type="audio/mpeg",
        sample_rate=24000,
        provider=provider,
        route_kind="provider",
        route_target=provider,
        latency_ms=50.0,
    )


def test_targeted_provider_fallback_resets_voice_for_edge() -> None:
    svc = TTSRouterService(_make_config())
    svc._index.synthesize = MagicMock(side_effect=RuntimeError("index timeout"))  # type: ignore[method-assign]
    svc._edge.synthesize = MagicMock(return_value=_ok_result("edge-tts"))  # type: ignore[method-assign]

    output = svc.synthesize(
        SynthesizeRequest(text="hello", voice_hint="jinping"),
        provider="index",
    )

    assert output.result.provider == "edge-tts"
    edge_request = svc._edge.synthesize.call_args.args[0]
    assert edge_request.voice_hint == ""

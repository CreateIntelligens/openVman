from __future__ import annotations

from unittest.mock import MagicMock

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.service import TTSRouterService


def _make_config() -> TTSRouterConfig:
    return TTSRouterConfig(
        _env_file=None,
        tts_indextts_url="http://index",
        tts_indextts_default_character="hayley",
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
    svc._indextts.synthesize = MagicMock(side_effect=RuntimeError("index timeout"))  # type: ignore[method-assign]
    svc._edge.synthesize = MagicMock(return_value=_ok_result("edge-tts"))  # type: ignore[method-assign]

    output = svc.synthesize(
        SynthesizeRequest(text="hello", voice_hint="jinping"),
        provider="indextts",
    )

    assert output.result.provider == "edge-tts"
    edge_request = svc._edge.synthesize.call_args.args[0]
    assert edge_request.voice_hint == ""


def _taiwanese_config() -> TTSRouterConfig:
    return TTSRouterConfig(
        _env_file=None,
        tts_cosyvoice_url="http://cosy",
        tts_voxcpm_url="http://vox",
        edge_tts_enabled=True,
        edge_tts_voice="zh-TW-HsiaoChenNeural",
    )


def test_partner_is_tried_in_the_mapped_voice_before_edge() -> None:
    svc = TTSRouterService(_taiwanese_config())
    svc._cosyvoice.synthesize = MagicMock(side_effect=RuntimeError("GPU 記憶體不足"))  # type: ignore[method-assign]
    svc._voxcpm.synthesize = MagicMock(return_value=_ok_result("voxcpm"))  # type: ignore[method-assign]
    svc._edge.synthesize = MagicMock(return_value=_ok_result("edge-tts"))  # type: ignore[method-assign]

    output = svc.synthesize(
        SynthesizeRequest(text="半月板受傷", voice_hint="young-female-02"),
        provider="cosyvoice",
        partners=(("voxcpm", "voxcpm2-cosy-young-female-02"),),
    )

    assert output.result.provider == "voxcpm"
    assert output.fallback is True
    assert "GPU" in output.fallback_reason
    assert svc._voxcpm.synthesize.call_args.args[0].voice_hint == "voxcpm2-cosy-young-female-02"
    svc._edge.synthesize.assert_not_called()


def test_edge_is_still_the_last_resort_when_the_partner_fails_too() -> None:
    svc = TTSRouterService(_taiwanese_config())
    svc._voxcpm.synthesize = MagicMock(side_effect=RuntimeError("vox down"))  # type: ignore[method-assign]
    svc._cosyvoice.synthesize = MagicMock(side_effect=RuntimeError("cosy down"))  # type: ignore[method-assign]
    svc._edge.synthesize = MagicMock(return_value=_ok_result("edge-tts"))  # type: ignore[method-assign]

    output = svc.synthesize(
        SynthesizeRequest(text="你好", voice_hint="voxcpm2-cosy-young-male-01"),
        provider="voxcpm",
        partners=(("cosyvoice", "young-male-01"),),
        edge_fallback_voice="zh-TW-YunJheNeural",
    )

    assert output.result.provider == "edge-tts"
    assert svc._cosyvoice.synthesize.call_args.args[0].voice_hint == "young-male-01"
    assert svc._edge.synthesize.call_args.args[0].voice_hint == "zh-TW-YunJheNeural"

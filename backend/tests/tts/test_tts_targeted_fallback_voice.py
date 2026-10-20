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


def test_project_order_replaces_the_deployment_chain_for_auto_requests() -> None:
    svc = TTSRouterService(_taiwanese_config())
    svc._voxcpm.synthesize = MagicMock(side_effect=RuntimeError("vox down"))  # type: ignore[method-assign]
    svc._cosyvoice.synthesize = MagicMock(return_value=_ok_result("cosyvoice"))  # type: ignore[method-assign]
    svc._edge.synthesize = MagicMock(return_value=_ok_result("edge-tts"))  # type: ignore[method-assign]

    chain = [t.target for t in svc.build_chain(order=("voxcpm", "cosyvoice"))]
    assert chain == ["voxcpm", "cosyvoice"]

    output = svc.synthesize(SynthesizeRequest(text="你好"), order=("voxcpm", "cosyvoice"))
    assert output.result.provider == "cosyvoice"
    # 順位裡沒有 Edge：就算有在跑也不會輪到它。
    svc._edge.synthesize.assert_not_called()


def test_project_order_does_not_override_an_explicit_provider() -> None:
    svc = TTSRouterService(_taiwanese_config())
    svc._cosyvoice.synthesize = MagicMock(return_value=_ok_result("cosyvoice"))  # type: ignore[method-assign]
    svc._voxcpm.synthesize = MagicMock(return_value=_ok_result("voxcpm"))  # type: ignore[method-assign]
    output = svc.synthesize(
        SynthesizeRequest(text="你好"), provider="cosyvoice", order=("voxcpm",),
    )
    assert output.result.provider == "cosyvoice"


def test_empty_audio_counts_as_a_failure_and_falls_through() -> None:
    svc = TTSRouterService(_taiwanese_config())
    from dataclasses import replace as dc_replace

    empty = dc_replace(_ok_result("cosyvoice"), audio_bytes=b"RIFF" + bytes(40))
    svc._cosyvoice.synthesize = MagicMock(return_value=empty)  # type: ignore[method-assign]
    svc._voxcpm.synthesize = MagicMock(return_value=_ok_result("voxcpm"))  # type: ignore[method-assign]
    output = svc.synthesize(
        SynthesizeRequest(text="你好", voice_hint="young-female-02"),
        provider="cosyvoice", partners=(("voxcpm", "voxcpm2-cosy-young-female-02"),),
    )
    assert output.result.provider == "voxcpm"
    assert output.fallback is True
    assert "bytes of audio" in output.fallback_reason


def test_stream_route_marks_fallback_on_buffered_audio() -> None:
    """/tts/stream 的整段合成回應也要像 /tts 一樣標出備援，不只換掉 X-TTS-Provider。"""
    from app.routes.tts import _buffered_audio
    from app.service import SynthesisOutput

    output = SynthesisOutput(
        result=_ok_result("voxcpm"), fallback=True, fallback_reason="cosyvoice: ConnectError",
    )
    plain = _buffered_audio(output, "", "cosyvoice")
    assert plain.headers["X-TTS-Provider"] == "voxcpm"
    assert plain.headers["X-TTS-Fallback"] == "true"
    assert plain.headers["X-TTS-Fallback-Reason"] == "cosyvoice: ConnectError"

    pcm = _buffered_audio(output, "pcm16k", "cosyvoice")
    assert pcm.headers["X-TTS-Provider"] == "voxcpm"
    assert pcm.headers["X-TTS-Fallback"] == "true"

    direct = _buffered_audio(SynthesisOutput(result=_ok_result("cosyvoice")), "", "cosyvoice")
    assert "X-TTS-Fallback" not in direct.headers

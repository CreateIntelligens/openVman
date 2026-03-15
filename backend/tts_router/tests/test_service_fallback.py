"""Tests for TTS router service fallback chain (TASK-14 + TASK-15)."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub external deps
# ---------------------------------------------------------------------------

sys.modules.setdefault("boto3", types.ModuleType("boto3"))

_fake_tts_mod = types.ModuleType("google.cloud.texttospeech")
_fake_tts_mod.TextToSpeechClient = MagicMock  # type: ignore[attr-defined]
_fake_tts_mod.SynthesisInput = MagicMock  # type: ignore[attr-defined]
_fake_tts_mod.VoiceSelectionParams = MagicMock  # type: ignore[attr-defined]
_fake_tts_mod.AudioConfig = MagicMock  # type: ignore[attr-defined]
_fake_tts_mod.AudioEncoding = types.SimpleNamespace(LINEAR16="LINEAR16")  # type: ignore[attr-defined]
sys.modules.setdefault("google", types.ModuleType("google"))
sys.modules.setdefault("google.cloud", types.ModuleType("google.cloud"))
sys.modules.setdefault("google.cloud.texttospeech", _fake_tts_mod)

from app.config import TTSRouterConfig
from app.observability import get_metrics_snapshot, reset_metrics
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.service import TTSRouterService


def _make_config(aws_enabled: bool = True, gcp_enabled: bool = True) -> TTSRouterConfig:
    return TTSRouterConfig(
        tts_aws_enabled=aws_enabled,
        tts_aws_region="ap-northeast-1",
        tts_aws_access_key_id="key",
        tts_aws_secret_access_key="secret",
        tts_aws_polly_voice_id="Zhiyu",
        tts_aws_polly_engine="neural",
        tts_aws_output_format="pcm",
        tts_aws_sample_rate=24000,
        tts_gcp_enabled=gcp_enabled,
        tts_gcp_project_id="test-proj",
        tts_gcp_voice_name="cmn-TW-Standard-A",
        tts_gcp_audio_encoding="LINEAR16",
        tts_gcp_sample_rate=24000,
    )


def _ok_result(provider: str = "aws") -> NormalizedTTSResult:
    return NormalizedTTSResult(
        audio_bytes=b"\x00\x01",
        content_type="audio/pcm",
        sample_rate=24000,
        provider=provider,
        route_kind="provider",
        route_target=f"{provider}-polly" if provider == "aws" else f"{provider}-tts",
        latency_ms=50.0,
    )


class TestRouterFallback:
    def setup_method(self):
        reset_metrics()

    def test_aws_success_returns_immediately(self):
        """AWS succeeds -> no GCP hop."""
        svc = TTSRouterService(_make_config())
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="hello"))
        assert result.provider == "aws"
        svc._gcp.synthesize.assert_not_called()

    def test_aws_fails_falls_back_to_gcp(self):
        """AWS fails -> GCP succeeds."""
        svc = TTSRouterService(_make_config())
        svc._aws.synthesize = MagicMock(side_effect=RuntimeError("aws down"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="hello"))
        assert result.provider == "gcp"

    def test_all_providers_fail_raises(self):
        """Both AWS and GCP fail -> RuntimeError."""
        svc = TTSRouterService(_make_config())
        svc._aws.synthesize = MagicMock(side_effect=RuntimeError("aws down"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(side_effect=RuntimeError("gcp down"))  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="所有 TTS fallback chain hops 皆失敗"):
            svc.synthesize(SynthesizeRequest(text="hello"))

    def test_router_returns_normalized_payload(self):
        """Router result has correct NormalizedTTSResult shape."""
        svc = TTSRouterService(_make_config())
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="test"))
        assert isinstance(result, NormalizedTTSResult)
        assert result.audio_bytes == b"\x00\x01"
        assert result.route_kind == "provider"

    def test_disabled_aws_skips_to_gcp(self):
        """AWS disabled -> chain only has GCP."""
        svc = TTSRouterService(_make_config(aws_enabled=False))
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="test"))
        assert result.provider == "gcp"

    def test_disabled_both_raises_empty_chain(self):
        """Both disabled -> empty chain error."""
        svc = TTSRouterService(_make_config(aws_enabled=False, gcp_enabled=False))
        with pytest.raises(RuntimeError, match="chain 為空"):
            svc.synthesize(SynthesizeRequest(text="test"))

    def test_chain_order_is_aws_then_gcp(self):
        """Verify the chain order: AWS first, then GCP."""
        svc = TTSRouterService(_make_config())
        chain = svc.build_chain()
        targets = [t.target for t in chain]
        assert targets == ["aws-polly", "gcp-tts"]

    def test_aws_success_stops_without_extra_hops(self):
        """After AWS success, no more hops are attempted."""
        svc = TTSRouterService(_make_config())
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        svc.synthesize(SynthesizeRequest(text="test"))

        snap = get_metrics_snapshot()
        success_keys = [k for k in snap["counters"] if "result=success" in k]
        assert len(success_keys) == 2  # route_attempt + provider_request for aws only
        # GCP should not appear in any success counter
        gcp_success = [k for k in success_keys if "gcp" in k]
        assert len(gcp_success) == 0

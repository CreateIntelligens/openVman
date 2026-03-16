"""Tests for TTS fallback metrics and observability (TASK-15)."""

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


def _make_config() -> TTSRouterConfig:
    return TTSRouterConfig(
        tts_aws_enabled=True,
        tts_aws_region="ap-northeast-1",
        tts_aws_access_key_id="key",
        tts_aws_secret_access_key="secret",
        tts_gcp_enabled=True,
        tts_gcp_project_id="test-proj",
    )


def _ok_result(provider: str = "aws") -> NormalizedTTSResult:
    target = "aws-polly" if provider == "aws" else "gcp-tts"
    return NormalizedTTSResult(
        audio_bytes=b"\x00",
        content_type="audio/pcm",
        sample_rate=24000,
        provider=provider,
        route_kind="provider",
        route_target=target,
        latency_ms=42.0,
    )


class TestFallbackMetrics:
    def setup_method(self):
        reset_metrics()

    def test_success_records_route_attempt(self):
        svc = TTSRouterService(_make_config())
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]

        svc.synthesize(SynthesizeRequest(text="hello"))
        snap = get_metrics_snapshot()

        attempt_keys = [k for k in snap["counters"] if "tts_route_attempts_total" in k and "success" in k]
        assert len(attempt_keys) >= 1

    def test_failure_records_provider_failure_counter(self):
        svc = TTSRouterService(_make_config())
        svc._gcp.synthesize = MagicMock(side_effect=RuntimeError("gcp down"))  # type: ignore[method-assign]
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]

        svc.synthesize(SynthesizeRequest(text="hello"))
        snap = get_metrics_snapshot()

        failure_keys = [k for k in snap["counters"] if "tts_provider_failures_total" in k]
        assert len(failure_keys) >= 1

    def test_fallback_hop_is_recorded(self):
        svc = TTSRouterService(_make_config())
        svc._gcp.synthesize = MagicMock(side_effect=RuntimeError("gcp fail"))  # type: ignore[method-assign]
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]

        svc.synthesize(SynthesizeRequest(text="hello"))
        snap = get_metrics_snapshot()

        hop_keys = [k for k in snap["counters"] if "tts_fallback_hops_total" in k]
        assert len(hop_keys) >= 1
        # Verify from/to targets
        hop_key = hop_keys[0]
        assert "gcp-tts" in hop_key
        assert "aws-polly" in hop_key

    def test_chain_exhausted_is_recorded(self):
        svc = TTSRouterService(_make_config())
        svc._aws.synthesize = MagicMock(side_effect=RuntimeError("aws down"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(side_effect=RuntimeError("gcp down"))  # type: ignore[method-assign]

        with pytest.raises(RuntimeError):
            svc.synthesize(SynthesizeRequest(text="hello"))

        snap = get_metrics_snapshot()
        exhausted_keys = [k for k in snap["counters"] if "tts_chain_exhausted_total" in k]
        assert len(exhausted_keys) >= 1

    def test_latency_is_recorded(self):
        svc = TTSRouterService(_make_config())
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        svc.synthesize(SynthesizeRequest(text="hello"))
        snap = get_metrics_snapshot()

        latency_keys = [k for k in snap["timings"] if "tts_provider_latency_ms" in k]
        assert len(latency_keys) >= 1
        assert snap["timings"][latency_keys[0]][0] >= 0

    def test_provider_request_counter(self):
        svc = TTSRouterService(_make_config())
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        svc.synthesize(SynthesizeRequest(text="hello"))
        snap = get_metrics_snapshot()

        req_keys = [k for k in snap["counters"] if "tts_provider_requests_total" in k and "gcp" in k]
        assert len(req_keys) >= 1

    def test_events_contain_route_attempt(self):
        svc = TTSRouterService(_make_config())
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        svc.synthesize(SynthesizeRequest(text="hello"))
        snap = get_metrics_snapshot()

        route_events = [e for e in snap["events"] if e["event"] == "tts_route_attempt"]
        assert len(route_events) >= 1
        evt = route_events[0]
        assert evt["kind"] == "provider"
        assert evt["target"] == "gcp-tts"
        assert evt["result"] == "success"
        assert "latency_ms" in evt

    def test_fallback_hop_event_contains_from_to(self):
        svc = TTSRouterService(_make_config())
        svc._gcp.synthesize = MagicMock(side_effect=RuntimeError("gcp fail"))  # type: ignore[method-assign]
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]

        svc.synthesize(SynthesizeRequest(text="hello"))
        snap = get_metrics_snapshot()

        hop_events = [e for e in snap["events"] if e["event"] == "tts_fallback_hop"]
        assert len(hop_events) >= 1
        evt = hop_events[0]
        assert evt["from_target"] == "gcp-tts"
        assert evt["to_target"] == "aws-polly"

    def test_chain_exhausted_event(self):
        svc = TTSRouterService(_make_config())
        svc._aws.synthesize = MagicMock(side_effect=RuntimeError("aws"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(side_effect=RuntimeError("gcp"))  # type: ignore[method-assign]

        with pytest.raises(RuntimeError):
            svc.synthesize(SynthesizeRequest(text="hello"))

        snap = get_metrics_snapshot()
        exhausted_events = [e for e in snap["events"] if e["event"] == "tts_chain_exhausted"]
        assert len(exhausted_events) == 1
        assert exhausted_events[0]["hops"] == 2

    def test_provider_chain_order_is_bounded(self):
        """Single request runs a bounded, fixed-order chain."""
        svc = TTSRouterService(_make_config())
        svc._aws.synthesize = MagicMock(side_effect=RuntimeError("aws"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(side_effect=RuntimeError("gcp"))  # type: ignore[method-assign]

        with pytest.raises(RuntimeError):
            svc.synthesize(SynthesizeRequest(text="hello"))

        snap = get_metrics_snapshot()
        attempt_events = [e for e in snap["events"] if e["event"] == "tts_route_attempt"]
        assert len(attempt_events) == 2
        assert attempt_events[0]["target"] == "gcp-tts"
        assert attempt_events[1]["target"] == "aws-polly"

"""Tests for TTS router service fallback chain."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.config import TTSRouterConfig
from app.observability import get_metrics_snapshot, reset_metrics
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.service import TTSRouterService


def _make_config(index_url: str = "http://index", aws_enabled: bool = True, gcp_enabled: bool = True, edge_enabled: bool = False) -> TTSRouterConfig:
    return TTSRouterConfig(
        tts_index_url=index_url,
        tts_index_character="hayley",
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
        edge_tts_enabled=edge_enabled,
    )


def _ok_result(provider: str = "aws") -> NormalizedTTSResult:
    target = f"{provider}-tts"
    if provider == "aws":
        target = "aws-polly"

    return NormalizedTTSResult(
        audio_bytes=b"\x00\x01",
        content_type="audio/pcm",
        sample_rate=24000,
        provider=provider,
        route_kind="provider",
        route_target=target,
        latency_ms=50.0,
    )


class TestRouterFallback:
    def setup_method(self):
        reset_metrics()

    def test_index_success_returns_immediately(self):
        """Index succeeds -> no GCP/AWS hop."""
        svc = TTSRouterService(_make_config())
        svc._index.synthesize = MagicMock(return_value=_ok_result("index"))  # type: ignore[method-assign]
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="hello"))
        assert result.provider == "index"
        svc._aws.synthesize.assert_not_called()
        svc._gcp.synthesize.assert_not_called()

    def test_index_fails_falls_back_to_gcp(self):
        """Index fails -> GCP succeeds."""
        svc = TTSRouterService(_make_config())
        svc._index.synthesize = MagicMock(side_effect=RuntimeError("index down"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="hello"))
        assert result.provider == "gcp"
        svc._aws.synthesize.assert_not_called()

    def test_index_gcp_fail_falls_back_to_aws(self):
        """Index, GCP fail -> AWS succeeds."""
        svc = TTSRouterService(_make_config())
        svc._index.synthesize = MagicMock(side_effect=RuntimeError("index down"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(side_effect=RuntimeError("gcp down"))  # type: ignore[method-assign]
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="hello"))
        assert result.provider == "aws"

    def test_all_providers_fail_raises(self):
        """Index, GCP and AWS fail -> RuntimeError."""
        svc = TTSRouterService(_make_config())
        svc._index.synthesize = MagicMock(side_effect=RuntimeError("index down"))  # type: ignore[method-assign]
        svc._aws.synthesize = MagicMock(side_effect=RuntimeError("aws down"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(side_effect=RuntimeError("gcp down"))  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="所有 TTS fallback chain hops 皆失敗"):
            svc.synthesize(SynthesizeRequest(text="hello"))

    def test_router_returns_normalized_payload(self):
        """Router result has correct NormalizedTTSResult shape."""
        svc = TTSRouterService(_make_config())
        svc._index.synthesize = MagicMock(return_value=_ok_result("index"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="test"))
        assert isinstance(result, NormalizedTTSResult)
        assert result.audio_bytes == b"\x00\x01"
        assert result.route_kind == "provider"

    def test_disabled_index_skips_to_gcp(self):
        """Index disabled -> chain starts with GCP."""
        svc = TTSRouterService(_make_config(index_url=""))
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="test"))
        assert result.provider == "gcp"

    def test_disabled_all_raises_empty_chain(self):
        """All disabled -> empty chain error."""
        svc = TTSRouterService(_make_config(index_url="", aws_enabled=False, gcp_enabled=False, edge_enabled=False))
        with pytest.raises(RuntimeError, match="chain 為空"):
            svc.synthesize(SynthesizeRequest(text="test"))

    def test_chain_order_is_index_then_gcp_then_aws(self):
        """Verify the chain order: Index first, then GCP, then AWS."""
        svc = TTSRouterService(_make_config())
        chain = svc.build_chain()
        targets = [t.target for t in chain]
        assert targets == ["index-tts", "gcp-tts", "aws-polly"]

    def test_index_success_stops_without_extra_hops(self):
        """After Index success, no more hops are attempted."""
        svc = TTSRouterService(_make_config())
        svc._index.synthesize = MagicMock(return_value=_ok_result("index"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        svc.synthesize(SynthesizeRequest(text="test"))

        snap = get_metrics_snapshot()
        success_keys = [k for k in snap["counters"] if "result=success" in k]
        # route_attempt + provider_request for index only
        assert len(success_keys) == 2
        index_success = [k for k in success_keys if "index" in k]
        assert len(index_success) == 2

    def test_aws_success_stops_without_extra_hops(self):
        """After AWS success, no more hops are attempted (requires Index and GCP to fail)."""
        svc = TTSRouterService(_make_config())
        svc._index.synthesize = MagicMock(side_effect=RuntimeError("index down"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(side_effect=RuntimeError("gcp down"))  # type: ignore[method-assign]
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]

        svc.synthesize(SynthesizeRequest(text="test"))

        snap = get_metrics_snapshot()
        success_keys = [k for k in snap["counters"] if "result=success" in k]
        # route_attempt + provider_request for aws only (index and gcp failed)
        assert len(success_keys) == 2
        aws_success = [k for k in success_keys if "aws" in k]
        assert len(aws_success) == 2

"""Integration tests: node → AWS → GCP full fallback chain."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from app.config import TTSRouterConfig
from app.node_health import NodeHealthPolicy
from app.observability import get_metrics_snapshot, reset_metrics
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.providers.node_adapter import NodeHTTPError
from app.service import TTSRouterService


def _config(**overrides) -> TTSRouterConfig:
    defaults = dict(
        tts_primary_node="http://primary:9000",
        tts_secondary_node="http://secondary:9000",
        tts_aws_enabled=True,
        tts_aws_region="ap-northeast-1",
        tts_aws_access_key_id="fake",
        tts_aws_secret_access_key="fake",
        tts_gcp_enabled=True,
        tts_gcp_project_id="fake",
        tts_gcp_credentials_json="{}",
        node_failure_threshold=2,
        node_cooldown_seconds=30.0,
        node_score_penalty=50,
        node_timeout_ms=5000,
    )
    defaults.update(overrides)
    return TTSRouterConfig(**defaults)


def _ok_result(target: str, kind: str = "node") -> NormalizedTTSResult:
    return NormalizedTTSResult(
        audio_bytes=b"\xff" * 100,
        content_type="audio/mpeg",
        sample_rate=24000,
        provider=kind,
        route_kind=kind,
        route_target=target,
        latency_ms=10.0,
    )


_REQUEST = SynthesizeRequest(text="你好")


@pytest.fixture(autouse=True)
def _clean_metrics():
    reset_metrics()
    yield
    reset_metrics()


class TestFullChain:
    """Test the complete node → AWS → GCP fallback chain."""

    def test_primary_node_success_returns_immediately(self):
        # Disable cloud providers to test node priority (though nodes are now last)
        svc = TTSRouterService(_config(tts_aws_enabled=False, tts_gcp_enabled=False))
        with patch.object(svc._node_adapters["tts-primary"], "synthesize", return_value=_ok_result("tts-primary")):
            result = svc.synthesize(_REQUEST)
        assert result.route_target == "tts-primary"
        assert result.route_kind == "node"

    def test_primary_fails_secondary_succeeds(self):
        svc = TTSRouterService(_config(tts_aws_enabled=False, tts_gcp_enabled=False))
        with (
            patch.object(svc._node_adapters["tts-primary"], "synthesize", side_effect=NodeHTTPError(500)),
            patch.object(svc._node_adapters["tts-secondary"], "synthesize", return_value=_ok_result("tts-secondary")),
        ):
            result = svc.synthesize(_REQUEST)
        assert result.route_target == "tts-secondary"

    def test_both_nodes_fail_raises(self):
        # When cloud providers are disabled and nodes fail
        svc = TTSRouterService(_config(tts_aws_enabled=False, tts_gcp_enabled=False))
        with (
            patch.object(svc._node_adapters["tts-primary"], "synthesize", side_effect=NodeHTTPError(500)),
            patch.object(svc._node_adapters["tts-secondary"], "synthesize", side_effect=NodeHTTPError(500)),
        ):
            with pytest.raises(RuntimeError):
                svc.synthesize(_REQUEST)

    def test_gcp_fails_falls_to_aws(self):
        svc = TTSRouterService(_config(tts_primary_node="", tts_secondary_node=""))
        with (
            patch.object(svc._gcp, "synthesize", side_effect=Exception("gcp down")),
            patch.object(svc._aws, "synthesize", return_value=_ok_result("aws-polly", "provider")),
        ):
            result = svc.synthesize(_REQUEST)
        assert result.route_target == "aws-polly"

    def test_gcp_aws_fail_falls_to_nodes(self):
        svc = TTSRouterService(_config())
        with (
            patch.object(svc._gcp, "synthesize", side_effect=Exception("gcp down")),
            patch.object(svc._aws, "synthesize", side_effect=Exception("aws down")),
            patch.object(svc._node_adapters["tts-primary"], "synthesize", return_value=_ok_result("tts-primary")),
        ):
            result = svc.synthesize(_REQUEST)
        assert result.route_target == "tts-primary"

    def test_chain_order_is_gcp_aws_nodes(self):
        svc = TTSRouterService(_config())
        chain = svc.build_chain()
        targets = [t.target for t in chain]
        # Order: GCP -> AWS -> Nodes
        assert targets == ["gcp-tts", "aws-polly", "tts-primary", "tts-secondary"]


class TestHealthIntegration:
    """Test that node health state affects chain building."""

    def test_unhealthy_node_bypassed(self):
        svc = TTSRouterService(_config(node_failure_threshold=1))
        svc._health.record_failure("tts-primary")
        chain = svc.build_chain()
        targets = [t.target for t in chain]
        assert "tts-primary" not in targets
        assert "tts-secondary" in targets

    def test_node_success_updates_health(self):
        svc = TTSRouterService(_config(tts_aws_enabled=False, tts_gcp_enabled=False))
        # Fail once
        svc._health.record_failure("tts-primary")
        assert svc._health.get_state("tts-primary").score == 50

        # Succeed via synthesize
        with patch.object(svc._node_adapters["tts-primary"], "synthesize", return_value=_ok_result("tts-primary")):
            svc.synthesize(_REQUEST)

        assert svc._health.get_state("tts-primary").score == 75
        assert svc._health.get_state("tts-primary").consecutive_failures == 0

    def test_node_failure_updates_health(self):
        svc = TTSRouterService(_config(tts_aws_enabled=False, tts_gcp_enabled=False))
        with (
            patch.object(svc._node_adapters["tts-primary"], "synthesize", side_effect=NodeHTTPError(500)),
            patch.object(svc._node_adapters["tts-secondary"], "synthesize", return_value=_ok_result("tts-secondary")),
        ):
            svc.synthesize(_REQUEST)
        assert svc._health.get_state("tts-primary").consecutive_failures == 1

    def test_no_nodes_configured_uses_providers_only(self):
        svc = TTSRouterService(_config(tts_primary_node="", tts_secondary_node=""))
        chain = svc.build_chain()
        targets = [t.target for t in chain]
        # Order: GCP -> AWS
        assert targets == ["gcp-tts", "aws-polly"]


class TestMetricsRecorded:
    """Test that metrics are properly emitted during node fallback."""

    def test_node_failover_recorded(self):
        svc = TTSRouterService(_config(tts_aws_enabled=False, tts_gcp_enabled=False))
        with (
            patch.object(svc._node_adapters["tts-primary"], "synthesize", side_effect=NodeHTTPError(500)),
            patch.object(svc._node_adapters["tts-secondary"], "synthesize", return_value=_ok_result("tts-secondary")),
        ):
            svc.synthesize(_REQUEST)

        snap = get_metrics_snapshot()
        events = snap["events"]
        failover_events = [e for e in events if e["event"] == "tts_node_failover"]
        assert len(failover_events) >= 1
        assert failover_events[0]["from_node"] == "tts-primary"
        assert failover_events[0]["to_target"] == "tts-secondary"

    def test_node_selected_recorded(self):
        svc = TTSRouterService(_config())
        with patch.object(svc._node_adapters["tts-primary"], "synthesize", return_value=_ok_result("tts-primary")):
            svc.synthesize(_REQUEST)

        snap = get_metrics_snapshot()
        events = snap["events"]
        selected = [e for e in events if e["event"] == "tts_node_selected"]
        assert any(e["node_id"] == "tts-primary" for e in selected)

    def test_node_bypassed_recorded(self):
        svc = TTSRouterService(_config(node_failure_threshold=1))
        svc._health.record_failure("tts-primary")

        with patch.object(svc._node_adapters["tts-secondary"], "synthesize", return_value=_ok_result("tts-secondary")):
            svc.synthesize(_REQUEST)

        snap = get_metrics_snapshot()
        events = snap["events"]
        bypassed = [e for e in events if e["event"] == "tts_node_bypassed"]
        assert any(e["node_id"] == "tts-primary" for e in bypassed)

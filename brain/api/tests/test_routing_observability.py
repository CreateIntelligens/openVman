"""TASK-24: Tests for routing observability and circuit-breaker metrics."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


# ---------------------------------------------------------------------------
# Stub setup
# ---------------------------------------------------------------------------

def _stub_deps(monkeypatch: pytest.MonkeyPatch):
    """Stub deps and return fresh modules with a real MetricsStore."""
    # Import the real observability module (it has no heavy deps)
    sys.modules.pop("safety.observability", None)
    observability = importlib.import_module("safety.observability")
    observability._metrics = None  # reset singleton

    fake_learnings = types.ModuleType("infra.learnings")
    fake_learnings.record_error_event = MagicMock()
    monkeypatch.setitem(sys.modules, "infra.learnings", fake_learnings)

    for mod in ("core.key_pool", "core.provider_router", "core.fallback_chain", "core.llm_client"):
        sys.modules.pop(mod, None)

    key_pool = importlib.import_module("core.key_pool")
    provider_router = importlib.import_module("core.provider_router")
    provider_router._router = None

    return observability, key_pool, provider_router


def _stub_config(monkeypatch, *, chain="", gemini_key="gk", groq_key="grk"):
    fake_cfg = MagicMock()
    fake_cfg.brain_llm_provider = "gemini"
    fake_cfg.brain_llm_model = "gemini-2.0-flash"
    fake_cfg.brain_llm_fallback_model = ""
    fake_cfg.brain_llm_api_key = gemini_key
    fake_cfg.brain_llm_api_keys = ""
    fake_cfg.brain_llm_base_url = ""
    fake_cfg.brain_llm_temperature = 0.3
    fake_cfg.brain_llm_fallback_chain = chain
    fake_cfg.brain_llm_max_fallback_hops = 4
    fake_cfg.brain_llm_key_cooldown_seconds = 60
    fake_cfg.brain_llm_key_long_cooldown_seconds = 300
    fake_cfg.gemini_api_key = gemini_key
    fake_cfg.groq_api_key = groq_key
    fake_cfg.openai_api_key = ""
    fake_cfg.resolved_llm_api_keys = [gemini_key] if gemini_key else []
    fake_cfg.resolved_llm_models = ["gemini-2.0-flash"]
    fake_cfg.resolved_llm_base_url = "https://api.example.com"
    fake_cfg.resolve_base_url_for_provider = lambda p: ""
    key_map = {"gemini": gemini_key, "groq": groq_key}
    fake_cfg.resolve_api_key_for_provider = lambda p: key_map.get(p, "")
    if chain.strip():
        pairs = []
        for entry in chain.split(","):
            if ":" in entry:
                prov, model = entry.strip().split(":", 1)
                pairs.append((prov.strip(), model.strip()))
        fake_cfg.resolved_fallback_chain = pairs
    else:
        fake_cfg.resolved_fallback_chain = [("gemini", "gemini-2.0-flash")]

    import config
    config._settings = None
    monkeypatch.setattr(config, "get_settings", lambda: fake_cfg)

    for mod_name in ("core.fallback_chain", "core.provider_router", "core.llm_client"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "get_settings"):
            monkeypatch.setattr(mod, "get_settings", lambda: fake_cfg)


# ---------------------------------------------------------------------------
# Metrics tests
# ---------------------------------------------------------------------------


class TestRoutingMetrics:
    def test_route_attempt_increments_counter(self, monkeypatch):
        """record_route_attempt should increment llm_route_attempts_total."""
        obs, _, _ = _stub_deps(monkeypatch)

        obs.record_route_attempt(
            trace_id="t1",
            provider="gemini",
            model="flash",
            hop_index=0,
            result="success",
            latency_ms=150.0,
        )

        snap = obs.get_metrics_store().snapshot()
        key = "llm_route_attempts_total|model=flash,provider=gemini,result=success"
        assert snap["counters"].get(key, 0) == 1

    def test_provider_failure_increments_failure_counter(self, monkeypatch):
        """Failed route should increment llm_provider_failures_total."""
        obs, _, _ = _stub_deps(monkeypatch)

        obs.record_route_attempt(
            trace_id="t2",
            provider="groq",
            model="llama",
            hop_index=0,
            result="failure",
            latency_ms=50.0,
            reason="rate_limited",
        )

        snap = obs.get_metrics_store().snapshot()
        failure_key = "llm_provider_failures_total|model=llama,provider=groq,reason=rate_limited"
        assert snap["counters"].get(failure_key, 0) == 1

    def test_fallback_hop_increments_counter(self, monkeypatch):
        """record_fallback_hop should increment llm_fallback_hops_total."""
        obs, _, _ = _stub_deps(monkeypatch)

        obs.record_fallback_hop(
            trace_id="t3",
            from_provider="gemini",
            from_model="flash",
            to_provider="groq",
            to_model="llama",
            reason="provider_error",
            hop_index=1,
        )

        snap = obs.get_metrics_store().snapshot()
        counters = snap["counters"]
        hop_keys = [k for k in counters if k.startswith("llm_fallback_hops_total")]
        assert len(hop_keys) == 1
        assert counters[hop_keys[0]] == 1

    def test_chain_exhausted_increments_counter(self, monkeypatch):
        """record_chain_exhausted should increment llm_chain_exhausted_total."""
        obs, _, _ = _stub_deps(monkeypatch)

        obs.record_chain_exhausted(trace_id="t4", final_reason="transient_error", hops=3)

        snap = obs.get_metrics_store().snapshot()
        key = "llm_chain_exhausted_total|final_reason=transient_error"
        assert snap["counters"].get(key, 0) == 1

    def test_route_latency_is_observed(self, monkeypatch):
        """record_route_attempt should observe llm_route_latency_ms."""
        obs, _, _ = _stub_deps(monkeypatch)

        obs.record_route_attempt(
            trace_id="t5",
            provider="gemini",
            model="flash",
            hop_index=0,
            result="success",
            latency_ms=200.5,
        )

        snap = obs.get_metrics_store().snapshot()
        latency_key = "llm_route_latency_ms|model=flash,provider=gemini,result=success"
        assert latency_key in snap["timings"]
        assert snap["timings"][latency_key]["count"] == 1
        assert snap["timings"][latency_key]["sum_ms"] == 200.5


# ---------------------------------------------------------------------------
# Circuit breaker state tests
# ---------------------------------------------------------------------------


class TestCircuitBreakerMetrics:
    def test_circuit_opens_after_threshold_failures(self, monkeypatch):
        """Circuit should open after _CIRCUIT_OPEN_THRESHOLD consecutive failures."""
        obs, key_pool, _ = _stub_deps(monkeypatch)

        pool = key_pool.KeyPoolManager(["k1"], short_cooldown=0.01)

        for _ in range(key_pool._CIRCUIT_OPEN_THRESHOLD):
            pool.mark_failure("k1", key_pool.FAILURE_TRANSIENT_ERROR)

        state = pool.get_state("k1")
        assert state.circuit_state == key_pool.CIRCUIT_OPEN

        # Verify metrics
        snap = obs.get_metrics_store().snapshot()
        state_keys = [k for k in snap["counters"] if "circuit_breaker_state_changes" in k]
        assert len(state_keys) >= 1

    def test_circuit_closes_on_success(self, monkeypatch):
        """Circuit should close after a successful request."""
        obs, key_pool, _ = _stub_deps(monkeypatch)

        pool = key_pool.KeyPoolManager(["k1"], short_cooldown=0.01)

        for _ in range(key_pool._CIRCUIT_OPEN_THRESHOLD):
            pool.mark_failure("k1", key_pool.FAILURE_TRANSIENT_ERROR)

        assert pool.get_state("k1").circuit_state == key_pool.CIRCUIT_OPEN

        pool.mark_success("k1")
        state = pool.get_state("k1")
        assert state.circuit_state == key_pool.CIRCUIT_CLOSED

    def test_circuit_state_change_is_logged(self, monkeypatch):
        """Circuit state changes should be recorded in metrics."""
        obs, key_pool, _ = _stub_deps(monkeypatch)

        pool = key_pool.KeyPoolManager(["k1"], short_cooldown=0.01)

        # Force open
        for _ in range(key_pool._CIRCUIT_OPEN_THRESHOLD):
            pool.mark_failure("k1", key_pool.FAILURE_TRANSIENT_ERROR)

        snap = obs.get_metrics_store().snapshot()
        open_key = [k for k in snap["counters"] if "state=open" in k]
        assert len(open_key) >= 1

    def test_auth_failure_opens_circuit_immediately(self, monkeypatch):
        """Auth invalid should immediately open circuit."""
        obs, key_pool, _ = _stub_deps(monkeypatch)

        pool = key_pool.KeyPoolManager(["k1"])
        pool.mark_failure("k1", key_pool.FAILURE_AUTH_INVALID)

        state = pool.get_state("k1")
        assert state.circuit_state == key_pool.CIRCUIT_OPEN
        assert state.disabled is True


# ---------------------------------------------------------------------------
# Integration test: metrics from actual chain execution
# ---------------------------------------------------------------------------


class TestChainExecutionMetrics:
    def test_chain_failure_produces_metrics(self, monkeypatch):
        """A failed chain execution should produce route attempt + chain exhausted metrics."""
        obs, key_pool, pr = _stub_deps(monkeypatch)
        _stub_config(
            monkeypatch,
            chain="gemini:m1,groq:m2",
            gemini_key="gk",
            groq_key="grk",
        )

        sys.modules.pop("core.llm_client", None)
        llm_client = importlib.import_module("core.llm_client")

        def always_fail(**kwargs):
            raise RuntimeError("fail")

        with patch("core.llm_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = always_fail
            mock_openai.return_value = mock_client

            with pytest.raises(RuntimeError):
                llm_client.generate_chat_turn(
                    [{"role": "user", "content": "hi"}],
                    trace_id="t-metrics",
                )

        snap = obs.get_metrics_store().snapshot()
        # Should have route attempt failures
        failure_keys = [
            k for k in snap["counters"]
            if k.startswith("llm_route_attempts_total") and "failure" in k
        ]
        assert len(failure_keys) >= 1

        # Should have chain exhausted
        exhausted_keys = [k for k in snap["counters"] if "chain_exhausted" in k]
        assert len(exhausted_keys) >= 1

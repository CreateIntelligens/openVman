"""TASK-22: Tests for key pool manager and quota-aware routing."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from time import monotonic
from unittest.mock import MagicMock

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


# ---------------------------------------------------------------------------
# Stub heavy modules
# ---------------------------------------------------------------------------

def _stub_deps(monkeypatch: pytest.MonkeyPatch):
    """Stub external deps so key_pool and provider_router can be imported."""
    # Stub infra.learnings
    fake_learnings = types.ModuleType("infra.learnings")
    fake_learnings.record_error_event = MagicMock()
    monkeypatch.setitem(sys.modules, "infra.learnings", fake_learnings)

    # Stub safety.observability
    fake_obs = types.ModuleType("safety.observability")
    fake_obs.log_event = MagicMock()
    fake_obs.log_exception = MagicMock()
    fake_obs.MetricsStore = MagicMock
    fake_obs.record_circuit_state_change = MagicMock()
    fake_obs.record_route_attempt = MagicMock()
    fake_obs.record_fallback_hop = MagicMock()
    fake_obs.record_chain_exhausted = MagicMock()
    monkeypatch.setitem(sys.modules, "safety.observability", fake_obs)

    # Force reimport
    for mod in ("core.key_pool", "core.provider_router"):
        sys.modules.pop(mod, None)

    key_pool = importlib.import_module("core.key_pool")
    provider_router = importlib.import_module("core.provider_router")
    # Reset singleton
    provider_router._router = None
    return key_pool, provider_router


# ---------------------------------------------------------------------------
# KeyPoolManager unit tests
# ---------------------------------------------------------------------------


class TestKeyPoolManager:
    def test_healthy_keys_are_selected_predictably(self, monkeypatch):
        """Round-robin among healthy keys produces predictable order."""
        key_pool, _ = _stub_deps(monkeypatch)
        pool = key_pool.KeyPoolManager(["k1", "k2", "k3"])

        selections = [pool.select_key() for _ in range(6)]
        # Should cycle through k1, k2, k3 in order
        assert selections == ["k1", "k2", "k3", "k1", "k2", "k3"]

    def test_exhausted_key_is_skipped_automatically(self, monkeypatch):
        """A key marked with quota_exhausted is skipped in selection."""
        key_pool, _ = _stub_deps(monkeypatch)
        pool = key_pool.KeyPoolManager(["k1", "k2"], long_cooldown=999.0)

        pool.mark_failure("k1", key_pool.FAILURE_QUOTA_EXHAUSTED)
        selections = [pool.select_key() for _ in range(3)]
        assert all(s == "k2" for s in selections)

    def test_invalid_key_is_disabled_after_auth_failure(self, monkeypatch):
        """An auth_invalid key gets permanently disabled."""
        key_pool, _ = _stub_deps(monkeypatch)
        pool = key_pool.KeyPoolManager(["k1", "k2"])

        pool.mark_failure("k1", key_pool.FAILURE_AUTH_INVALID)

        state = pool.get_state("k1")
        assert state.disabled is True
        assert state.healthy is False

        # k1 should never be selected
        selections = [pool.select_key() for _ in range(3)]
        assert all(s == "k2" for s in selections)

    def test_rate_limited_key_enters_short_cooldown(self, monkeypatch):
        """Rate limited key enters short cooldown (not disabled)."""
        key_pool, _ = _stub_deps(monkeypatch)
        pool = key_pool.KeyPoolManager(
            ["k1", "k2"], short_cooldown=0.05, long_cooldown=999.0
        )

        pool.mark_failure("k1", key_pool.FAILURE_RATE_LIMITED)

        state = pool.get_state("k1")
        assert state.disabled is False
        assert state.cooldown_until > monotonic()

    def test_success_resets_failures(self, monkeypatch):
        """mark_success resets consecutive failures and cooldown."""
        key_pool, _ = _stub_deps(monkeypatch)
        pool = key_pool.KeyPoolManager(["k1"])

        pool.mark_failure("k1", key_pool.FAILURE_TRANSIENT_ERROR)
        assert pool.get_state("k1").consecutive_failures == 1

        pool.mark_success("k1")
        state = pool.get_state("k1")
        assert state.consecutive_failures == 0
        assert state.healthy is True
        assert state.cooldown_until == 0.0

    def test_all_keys_in_cooldown_returns_earliest(self, monkeypatch):
        """When all keys are in cooldown, select_key returns the earliest-expiring one."""
        key_pool, _ = _stub_deps(monkeypatch)
        pool = key_pool.KeyPoolManager(
            ["k1", "k2"], short_cooldown=100.0, long_cooldown=999.0
        )

        pool.mark_failure("k1", key_pool.FAILURE_RATE_LIMITED)
        pool.mark_failure("k2", key_pool.FAILURE_RATE_LIMITED)

        # k1 was marked first, so its cooldown_until is earlier
        selected = pool.select_key()
        assert selected == "k1"

    def test_all_states_returns_snapshot(self, monkeypatch):
        """all_states returns a snapshot of all key states."""
        key_pool, _ = _stub_deps(monkeypatch)
        pool = key_pool.KeyPoolManager(["k1", "k2"])

        states = pool.all_states
        assert len(states) == 2
        assert all(s.healthy for s in states)


# ---------------------------------------------------------------------------
# Failure classification tests
# ---------------------------------------------------------------------------


class TestFailureClassification:
    def test_classify_401_as_auth_invalid(self, monkeypatch):
        key_pool, _ = _stub_deps(monkeypatch)
        result = key_pool.classify_failure(_make_api_status_error(401))
        assert result == key_pool.FAILURE_AUTH_INVALID

    def test_classify_403_as_auth_forbidden(self, monkeypatch):
        key_pool, _ = _stub_deps(monkeypatch)
        result = key_pool.classify_failure(_make_api_status_error(403))
        assert result == key_pool.FAILURE_AUTH_FORBIDDEN

    def test_classify_429_rate_limit_as_rate_limited(self, monkeypatch):
        key_pool, _ = _stub_deps(monkeypatch)
        from openai import RateLimitError

        exc = _make_rate_limit_error("rate limit exceeded")
        result = key_pool.classify_failure(exc)
        assert result == key_pool.FAILURE_RATE_LIMITED

    def test_classify_429_quota_as_quota_exhausted(self, monkeypatch):
        key_pool, _ = _stub_deps(monkeypatch)

        exc = _make_rate_limit_error("quota exhausted")
        result = key_pool.classify_failure(exc)
        assert result == key_pool.FAILURE_QUOTA_EXHAUSTED

    def test_classify_500_as_provider_error(self, monkeypatch):
        key_pool, _ = _stub_deps(monkeypatch)
        result = key_pool.classify_failure(_make_api_status_error(500))
        assert result == key_pool.FAILURE_PROVIDER_ERROR

    def test_classify_timeout_as_transient(self, monkeypatch):
        key_pool, _ = _stub_deps(monkeypatch)
        from openai import APITimeoutError

        exc = APITimeoutError(request=MagicMock())
        result = key_pool.classify_failure(exc)
        assert result == key_pool.FAILURE_TRANSIENT_ERROR


# ---------------------------------------------------------------------------
# ProviderRouter integration tests
# ---------------------------------------------------------------------------


class TestProviderRouterIntegration:
    def test_iter_routes_returns_routes(self, monkeypatch):
        key_pool, pr = _stub_deps(monkeypatch)
        _stub_config(monkeypatch, keys=["key-a", "key-b"], models=["gpt-4"])

        # Reset config singleton so stub takes effect
        import config
        config._settings = None

        router = pr.ProviderRouter()
        routes = router.iter_routes()
        assert len(routes) >= 1
        assert all(isinstance(r, pr.LLMRoute) for r in routes)

    def test_mark_failure_disables_auth_invalid_key(self, monkeypatch):
        key_pool, pr = _stub_deps(monkeypatch)

        # Create router with explicit pool to avoid config dependency
        router = pr.ProviderRouter()
        pool = key_pool.KeyPoolManager(["key-a", "key-b"])
        router._pool = pool

        exc = _make_api_status_error(401)
        router.mark_failure("key-a", "gpt-4", exc)

        state = pool.get_state("key-a")
        assert state.disabled is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_config(
    monkeypatch: pytest.MonkeyPatch,
    keys: list[str],
    models: list[str],
):
    """Stub config.get_settings for provider router tests."""
    fake_cfg = MagicMock()
    fake_cfg.resolved_llm_api_keys = keys
    fake_cfg.resolved_llm_models = models
    fake_cfg.resolved_llm_base_url = "https://api.example.com"
    fake_cfg.llm_key_cooldown_seconds = 60
    fake_cfg.llm_key_long_cooldown_seconds = 300

    import config
    import core.provider_router as _pr_mod
    monkeypatch.setattr(config, "get_settings", lambda: fake_cfg)
    monkeypatch.setattr(_pr_mod, "get_settings", lambda: fake_cfg)


def _make_api_status_error(status_code: int):
    """Create a minimal APIStatusError with the given status code."""
    from openai import APIStatusError
    from unittest.mock import MagicMock

    response = MagicMock()
    response.status_code = status_code
    response.headers = {}
    response.text = ""

    try:
        raise APIStatusError(
            message=f"Error {status_code}",
            response=response,
            body={"error": {"message": f"Error {status_code}"}},
        )
    except APIStatusError as exc:
        return exc


def _make_rate_limit_error(message: str):
    """Create a RateLimitError with a specific message."""
    from openai import RateLimitError
    from unittest.mock import MagicMock

    response = MagicMock()
    response.status_code = 429
    response.headers = {}
    response.text = ""

    try:
        raise RateLimitError(
            message=message,
            response=response,
            body={"error": {"message": message}},
        )
    except RateLimitError as exc:
        return exc

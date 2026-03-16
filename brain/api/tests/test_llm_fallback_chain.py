"""TASK-23: Tests for model and provider fallback chain execution."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


# ---------------------------------------------------------------------------
# Stub heavy modules
# ---------------------------------------------------------------------------

def _stub_deps(monkeypatch: pytest.MonkeyPatch):
    """Stub external deps for fallback chain testing."""
    fake_learnings = types.ModuleType("infra.learnings")
    fake_learnings.record_error_event = MagicMock()
    monkeypatch.setitem(sys.modules, "infra.learnings", fake_learnings)

    fake_obs = types.ModuleType("safety.observability")
    logged_events: list[dict] = []

    def _log_event(event_type, **kwargs):
        logged_events.append({"event": event_type, **kwargs})

    fake_obs.log_event = _log_event
    fake_obs.log_exception = MagicMock()
    fake_obs.MetricsStore = MagicMock
    fake_obs.record_circuit_state_change = MagicMock()
    fake_obs.record_route_attempt = lambda **kwargs: _log_event("llm_route_attempt", **kwargs)
    fake_obs.record_fallback_hop = lambda **kwargs: _log_event("llm_fallback_hop", **kwargs)
    fake_obs.record_chain_exhausted = lambda **kwargs: _log_event("llm_chain_exhausted", **kwargs)
    fake_obs.get_metrics_store = MagicMock()
    monkeypatch.setitem(sys.modules, "safety.observability", fake_obs)

    # Force reimport chain modules
    for mod in (
        "core.key_pool",
        "core.provider_router",
        "core.fallback_chain",
        "core.llm_client",
    ):
        sys.modules.pop(mod, None)

    fallback_chain = importlib.import_module("core.fallback_chain")
    provider_router = importlib.import_module("core.provider_router")
    provider_router._router = None

    return fallback_chain, provider_router, logged_events


def _stub_config(
    monkeypatch,
    *,
    chain: str = "",
    max_hops: int = 4,
    primary_provider: str = "gemini",
    primary_model: str = "gemini-2.0-flash",
    fallback_model: str = "",
    primary_key: str = "key-primary",
    gemini_key: str = "",
    groq_key: str = "",
    openai_key: str = "",
):
    fake_cfg = MagicMock()
    fake_cfg.brain_llm_provider = primary_provider
    fake_cfg.brain_llm_model = primary_model
    fake_cfg.brain_llm_fallback_model = fallback_model
    fake_cfg.brain_llm_api_key = primary_key
    fake_cfg.brain_llm_api_keys = ""
    fake_cfg.brain_llm_base_url = ""
    fake_cfg.brain_llm_temperature = 0.3
    fake_cfg.brain_llm_fallback_chain = chain
    fake_cfg.brain_llm_max_fallback_hops = max_hops
    fake_cfg.brain_llm_key_cooldown_seconds = 60
    fake_cfg.brain_llm_key_long_cooldown_seconds = 300
    fake_cfg.gemini_api_key = gemini_key
    fake_cfg.groq_api_key = groq_key
    fake_cfg.openai_api_key = openai_key

    # Wire up properties
    fake_cfg.resolved_llm_api_keys = [primary_key] if primary_key else []
    fake_cfg.resolved_llm_models = [primary_model]
    if fallback_model:
        fake_cfg.resolved_llm_models.append(fallback_model)
    fake_cfg.resolved_llm_base_url = "https://api.example.com"

    # Implement resolve methods
    base_urls = {
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "groq": "https://api.groq.com/openai/v1",
    }
    key_map = {
        primary_provider: primary_key,
        "gemini": gemini_key or (primary_key if primary_provider == "gemini" else ""),
        "groq": groq_key,
        "openai": openai_key,
    }

    fake_cfg.resolve_base_url_for_provider = lambda p: base_urls.get(p, "")
    fake_cfg.resolve_api_key_for_provider = lambda p: key_map.get(p, "")

    # Parse chain
    if chain.strip():
        pairs = []
        for entry in chain.split(","):
            entry = entry.strip()
            if ":" in entry:
                prov, model = entry.split(":", 1)
                pairs.append((prov.strip(), model.strip()))
        fake_cfg.resolved_fallback_chain = pairs
    else:
        fake_cfg.resolved_fallback_chain = [
            (primary_provider, m) for m in fake_cfg.resolved_llm_models
        ]

    import config
    config._settings = None
    monkeypatch.setattr(config, "get_settings", lambda: fake_cfg)

    # Also patch references in already-imported modules
    for mod_name in ("core.fallback_chain", "core.provider_router", "core.llm_client"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "get_settings"):
            monkeypatch.setattr(mod, "get_settings", lambda: fake_cfg)


# ---------------------------------------------------------------------------
# Chain building tests
# ---------------------------------------------------------------------------


class TestBuildFallbackChain:
    def test_chain_built_from_config(self, monkeypatch):
        fc, _, events = _stub_deps(monkeypatch)
        _stub_config(
            monkeypatch,
            chain="gemini:gemini-2.0-flash,groq:llama-3.3-70b",
            gemini_key="gk1",
            groq_key="grk1",
        )

        hops = fc.build_fallback_chain("trace-1")
        assert len(hops) == 2
        assert hops[0].provider == "gemini"
        assert hops[0].model == "gemini-2.0-flash"
        assert hops[1].provider == "groq"
        assert hops[1].model == "llama-3.3-70b"
        assert all(h.trace_id == "trace-1" for h in hops)

    def test_chain_respects_max_hops(self, monkeypatch):
        fc, _, _ = _stub_deps(monkeypatch)
        _stub_config(
            monkeypatch,
            chain="gemini:m1,gemini:m2,groq:m3,openai:m4,gemini:m5",
            max_hops=3,
            gemini_key="gk",
            groq_key="grk",
            openai_key="ok",
        )

        hops = fc.build_fallback_chain("trace-2")
        assert len(hops) <= 3

    def test_chain_skips_providers_without_key(self, monkeypatch):
        fc, _, _ = _stub_deps(monkeypatch)
        _stub_config(
            monkeypatch,
            chain="gemini:m1,groq:m2,openai:m3",
            gemini_key="gk",
            groq_key="",
            openai_key="ok",
        )

        hops = fc.build_fallback_chain("trace-3")
        providers = [h.provider for h in hops]
        assert "groq" not in providers
        assert "gemini" in providers
        assert "openai" in providers

    def test_default_chain_uses_primary_provider(self, monkeypatch):
        fc, _, _ = _stub_deps(monkeypatch)
        _stub_config(monkeypatch, chain="")

        hops = fc.build_fallback_chain("trace-4")
        assert len(hops) >= 1
        assert hops[0].provider == "gemini"


# ---------------------------------------------------------------------------
# Fallback execution tests
# ---------------------------------------------------------------------------


class TestFallbackExecution:
    def test_429_triggers_next_hop(self, monkeypatch):
        """429 on first hop should trigger fallback to next hop."""
        fc, pr, events = _stub_deps(monkeypatch)
        _stub_config(
            monkeypatch,
            chain="gemini:m1,groq:m2",
            gemini_key="gk",
            groq_key="grk",
        )

        # Import llm_client fresh
        sys.modules.pop("core.llm_client", None)
        llm_client = importlib.import_module("core.llm_client")

        call_count = {"n": 0}

        def fake_create(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                from openai import RateLimitError
                response = MagicMock()
                response.status_code = 429
                response.headers = {}
                response.text = ""
                raise RateLimitError(
                    message="rate limit",
                    response=response,
                    body={"error": {"message": "rate limit"}},
                )
            # Second call succeeds
            msg = MagicMock()
            msg.content = "fallback response"
            msg.tool_calls = None
            choice = MagicMock()
            choice.message = msg
            resp = MagicMock()
            resp.choices = [choice]
            resp.model = "m2"
            return resp

        with patch("core.llm_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = fake_create
            mock_openai.return_value = mock_client

            reply = llm_client.generate_chat_turn(
                [{"role": "user", "content": "hi"}],
                trace_id="t-429",
            )

        assert reply.content == "fallback response"
        assert call_count["n"] == 2

        # Verify route attempt events were logged
        route_attempts = [e for e in events if e["event"] == "llm_route_attempt"]
        assert len(route_attempts) == 2

    def test_bounded_chain_stops_after_max_hops(self, monkeypatch):
        """Chain should stop after max hops even if all fail."""
        fc, pr, events = _stub_deps(monkeypatch)
        _stub_config(
            monkeypatch,
            chain="gemini:m1,groq:m2",
            max_hops=2,
            gemini_key="gk",
            groq_key="grk",
        )

        sys.modules.pop("core.llm_client", None)
        llm_client = importlib.import_module("core.llm_client")

        def always_fail(**kwargs):
            raise RuntimeError("always fail")

        with patch("core.llm_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = always_fail
            mock_openai.return_value = mock_client

            with pytest.raises(RuntimeError, match="所有 fallback chain hops 皆失敗"):
                llm_client.generate_chat_turn(
                    [{"role": "user", "content": "hi"}],
                    trace_id="t-bounded",
                )

    def test_trace_id_preserved_across_hops(self, monkeypatch):
        """All hops in a chain share the same trace_id."""
        fc, _, events = _stub_deps(monkeypatch)
        _stub_config(
            monkeypatch,
            chain="gemini:m1,groq:m2",
            gemini_key="gk",
            groq_key="grk",
        )

        hops = fc.build_fallback_chain("trace-preserve")
        assert all(h.trace_id == "trace-preserve" for h in hops)

    def test_5xx_triggers_next_hop(self, monkeypatch):
        """5xx on first hop should trigger fallback to next hop."""
        fc, pr, events = _stub_deps(monkeypatch)
        _stub_config(
            monkeypatch,
            chain="gemini:m1,groq:m2",
            gemini_key="gk",
            groq_key="grk",
        )

        sys.modules.pop("core.llm_client", None)
        llm_client = importlib.import_module("core.llm_client")

        call_count = {"n": 0}

        def fake_create(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                from openai import APIStatusError
                response = MagicMock()
                response.status_code = 500
                response.headers = {}
                response.text = ""
                raise APIStatusError(
                    message="internal error",
                    response=response,
                    body={},
                )
            msg = MagicMock()
            msg.content = "recovered"
            msg.tool_calls = None
            choice = MagicMock()
            choice.message = msg
            resp = MagicMock()
            resp.choices = [choice]
            resp.model = "m2"
            return resp

        with patch("core.llm_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = fake_create
            mock_openai.return_value = mock_client

            reply = llm_client.generate_chat_turn(
                [{"role": "user", "content": "hi"}],
                trace_id="t-5xx",
            )

        assert reply.content == "recovered"

    def test_router_logs_each_hop_decision(self, monkeypatch):
        """Each hop attempt and result should be logged."""
        fc, pr, events = _stub_deps(monkeypatch)
        _stub_config(
            monkeypatch,
            chain="gemini:m1,groq:m2",
            gemini_key="gk",
            groq_key="grk",
        )

        sys.modules.pop("core.llm_client", None)
        llm_client = importlib.import_module("core.llm_client")

        def succeed(**kwargs):
            msg = MagicMock()
            msg.content = "ok"
            msg.tool_calls = None
            choice = MagicMock()
            choice.message = msg
            resp = MagicMock()
            resp.choices = [choice]
            resp.model = "m1"
            return resp

        with patch("core.llm_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = succeed
            mock_openai.return_value = mock_client

            llm_client.generate_chat_turn(
                [{"role": "user", "content": "hi"}],
                trace_id="t-log",
            )

        # Should have chain_built and route_attempt
        event_types = [e["event"] for e in events]
        assert "fallback_chain_built" in event_types
        assert "llm_route_attempt" in event_types

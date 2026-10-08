from __future__ import annotations

import asyncio
import threading
from time import monotonic

import httpx
import pytest

from core import decision_router as router


def _config(providers):
    return router._ProviderConfiguration(tuple(providers))


def _hop(hop_id, *, api_key="key"):
    provider, endpoint, model, required = router._EXPECTED_HOPS[hop_id]
    return router.DecisionProvider(hop_id, provider, endpoint, model, api_key, required)


def test_openai_payload_maps_systemone_question_types():
    hop = _hop("openai")
    questions = {
        "is_relevant": {
            "type": "noul", "instructions": "Relevant?",
            "criteria": {"true": "Directly related", "false": "Unrelated"},
        },
        "route": {
            "type": "choice", "instructions": "Choose a route",
            "criteria": {"chat": "Conversation", "web": "Current information"},
        },
        "severity": {"type": "score", "criteria": ["low", "high"]},
    }

    payload = router._openai_payload(hop, {"text": "sample"}, questions)

    assert payload["model"] == "gpt-6-luna"
    assert payload["input"] == '{"text": "sample"}'
    assert payload["questions"][0]["type"] == "predicate"
    assert "Directly related" in payload["questions"][0]["instructions"]
    assert payload["questions"][1]["choices"] == [
        {"value": "chat", "description": "Conversation"},
        {"value": "web", "description": "Current information"},
    ]
    assert payload["questions"][2]["levels"] == [
        {"label": "low", "description": ""},
        {"label": "high", "description": ""},
    ]


def test_openai_answers_normalize_predicate_choice_and_score():
    questions = {
        "yes": {"type": "noul"},
        "route": {"type": "choice", "criteria": {"chat": "", "web": ""}},
        "severity": {"type": "score", "criteria": ["low", "high"]},
    }
    body = {"answers": [
        {"type": "predicate", "name": "yes", "probability": 0.9},
        {"type": "choice", "name": "route", "choice": "web", "confidence": 0.8,
         "probabilities": [{"value": "chat", "probability": 0.2}, {"value": "web", "probability": 0.8}]},
        {"type": "score", "name": "severity", "score": 0.7, "confidence": 0.6},
    ]}

    answers = router._parse_answers("openai", body, questions)

    assert answers["yes"] == {"type": "noul", "noul": 0.9}
    assert answers["route"]["choice"] == "web"
    assert answers["route"]["probabilities"] == {"chat": 0.2, "web": 0.8}
    assert answers["severity"]["score"] == 0.7


def test_chain_falls_through_failed_clef_hop_to_jev(monkeypatch):
    monkeypatch.setattr(router, "_provider_configuration", lambda **_: _config([
        _hop("clef-primary", api_key=""), _hop("jev"),
    ]))
    attempts = []

    def call(hop, state, questions, *, timeout):
        attempts.append(hop.id)
        if hop.id == "clef-primary":
            raise httpx.ConnectError("offline")
        return {"answers": {"q": {"type": "noul", "noul": 0.75}}, "usage": {}}

    records = []
    monkeypatch.setattr(router, "_call_provider", call)
    monkeypatch.setattr(router, "_record_hop", lambda **kw: records.append(kw))

    result = router.decide("state", {"q": {"type": "noul"}}, timeout=1, purpose="test")

    assert attempts == ["clef-primary", "jev"]
    assert result.provider == "jev"
    assert result.answers["q"]["noul"] == 0.75
    assert [record["status"] for record in records] == ["connection_error", "ok"]


def test_clef_primary_success_short_circuits_the_chain(monkeypatch):
    hops = [_hop(name) for name in ("clef-primary", "clef-backup", "jev", "openai")]
    monkeypatch.setattr(router, "_provider_configuration", lambda **_: _config(hops))
    attempts = []

    def call(hop, state, questions, *, timeout):
        attempts.append(hop.id)
        return {"answers": {"q": {"type": "noul", "noul": 0.9}}}

    monkeypatch.setattr(router, "_call_provider", call)
    monkeypatch.setattr(router, "_record_hop", lambda **_: None)
    result = router.decide("state", {"q": {"type": "noul"}}, timeout=1, purpose="decision_turn")

    assert result.hop_id == "clef-primary"
    assert attempts == ["clef-primary"]


def test_chain_all_four_hops_fail_and_records_each_attempt(monkeypatch):
    hops = [_hop(name) for name in ("clef-primary", "clef-backup", "jev", "openai")]
    monkeypatch.setattr(router, "_provider_configuration", lambda **_: _config(hops))
    attempts = []
    records = []

    def call(hop, state, questions, *, timeout):
        attempts.append(hop.id)
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(router, "_call_provider", call)
    monkeypatch.setattr(router, "_record_hop", lambda **kwargs: records.append(kwargs))

    with pytest.raises(router.DecisionProviderError, match="all decision providers failed"):
        router.decide("state", {"q": {"type": "noul"}}, timeout=2, purpose="decision_turn")

    assert attempts == [hop.id for hop in hops]
    assert [record["status"] for record in records] == ["connection_error"] * 4


def test_empty_provider_chain_uses_no_provider_and_returns_failure(monkeypatch):
    monkeypatch.setattr(router, "_provider_configuration", lambda **_: _config([]))
    monkeypatch.setattr(router, "_call_provider", lambda *a, **kw: pytest.fail("no provider should run"))

    with pytest.raises(router.DecisionProviderError, match="all decision providers failed"):
        router.decide("state", {"q": {"type": "noul"}}, timeout=1, purpose="decision_turn")


def test_optional_per_hop_cap_preserves_provider_failover(monkeypatch):
    monkeypatch.setattr(router, "_provider_configuration", lambda **_: _config([
        _hop("clef-primary", api_key=""), _hop("clef-backup", api_key=""),
    ]))
    budgets = []
    attempts = []
    monkeypatch.setattr(router, "_record_hop", lambda **_: None)

    def call(hop, state, questions, *, timeout):
        attempts.append(hop.id)
        budgets.append(timeout)
        if hop.id == "clef-primary":
            raise httpx.ConnectError("offline")
        return {"answers": {"q": {"type": "noul", "noul": 0.8}}}

    monkeypatch.setattr(router, "_call_provider", call)
    result = router.decide(
        "state", {"q": {"type": "noul"}}, timeout=1.0,
        per_hop_timeout=0.1, purpose="test",
    )

    assert attempts == ["clef-primary", "clef-backup"]
    assert all(budget <= 0.1 for budget in budgets)
    assert result.hop_id == "clef-backup"


def test_already_cancelled_turn_does_not_fetch_provider_configuration(monkeypatch):
    event = threading.Event()
    event.set()
    monkeypatch.setattr(router, "_provider_configuration", lambda **_: pytest.fail("should stop before config"))

    with pytest.raises(router.DecisionProviderCancelled):
        router.decide(
            "state", {"q": {"type": "noul"}}, timeout=1,
            purpose="test", cancel_event=event,
        )


def test_chain_skips_missing_required_credentials(monkeypatch):
    monkeypatch.setattr(router, "_provider_configuration", lambda **_: _config([
        _hop("jev", api_key=""), _hop("openai"),
    ]))
    attempts = []
    records = []

    def call(hop, state, questions, *, timeout):
        attempts.append(hop.id)
        return {"answers": [{"name": "q", "type": "predicate", "probability": 0.6}]}

    monkeypatch.setattr(router, "_call_provider", call)
    monkeypatch.setattr(router, "_record_hop", lambda **kw: records.append(kw))

    result = router.decide("state", {"q": {"type": "noul"}}, timeout=1, purpose="test")

    assert attempts == ["openai"]
    assert records[0]["status"] == "missing_key"
    assert result.hop_id == "openai"


def test_refusal_advances_to_next_provider(monkeypatch):
    monkeypatch.setattr(router, "_provider_configuration", lambda **_: _config([
        _hop("openai"), _hop("jev"),
    ]))
    attempts = []
    records = []

    def call(hop, state, questions, *, timeout):
        attempts.append(hop.id)
        if hop.id == "openai":
            return {"answers": [{"type": "refusal", "name": "q"}]}
        return {"answers": {"q": {"type": "noul", "noul": 0.8}}}

    monkeypatch.setattr(router, "_call_provider", call)
    monkeypatch.setattr(router, "_record_hop", lambda **kw: records.append(kw))

    result = router.decide("state", {"q": {"type": "noul"}}, timeout=1, purpose="test")

    assert attempts == ["openai", "jev"]
    assert records[0]["status"] == "invalid_response"
    assert result.provider == "jev"


def test_invalid_shared_questions_fail_before_provider_attempt(monkeypatch):
    monkeypatch.setattr(router, "_provider_configuration", lambda **_: pytest.fail("must not fetch config"))

    with pytest.raises(ValueError):
        router.decide("state", {"q": {"type": "unknown"}}, timeout=1, purpose="test")


def test_oversized_decision_input_is_rejected_before_network(monkeypatch):
    monkeypatch.setattr(router, "_provider_configuration", lambda **_: pytest.fail("must not fetch config"))

    with pytest.raises(ValueError, match="size limit"):
        router.decide("x" * (65 * 1024), {"q": {"type": "noul"}}, timeout=1, purpose="test")


def test_configuration_unavailable_without_cached_config_fails_closed(monkeypatch):
    router.clear_provider_configuration_cache()
    monkeypatch.setattr(
        router, "_fetch_provider_configuration",
        lambda **_: (_ for _ in ()).throw(httpx.ConnectError("backend offline")),
    )

    with pytest.raises(router.DecisionProviderError, match="configuration unavailable"):
        router._provider_configuration(timeout=0.1)


def test_expired_configuration_uses_last_known_good_after_backend_failure(monkeypatch):
    router.clear_provider_configuration_cache()
    last_good = _config([_hop("openai")])
    monkeypatch.setattr(router, "_fetch_provider_configuration", lambda **_: last_good)
    assert router._provider_configuration(timeout=0.1) == last_good
    router._CONFIG_CACHE_AT = 0
    monkeypatch.setattr(
        router, "_fetch_provider_configuration",
        lambda **_: (_ for _ in ()).throw(httpx.ConnectError("backend offline")),
    )

    assert router._provider_configuration(timeout=0.1) == last_good


def test_invalid_choice_contract_fails_before_fetching_config(monkeypatch):
    monkeypatch.setattr(router, "_provider_configuration", lambda **_: pytest.fail("must not fetch config"))

    with pytest.raises(ValueError, match="choice questions"):
        router.decide("state", {"q": {"type": "choice", "criteria": {"only": "one"}}}, timeout=1, purpose="test")


def test_score_outside_levels_falls_through_to_next_provider(monkeypatch):
    monkeypatch.setattr(router, "_provider_configuration", lambda **_: _config([
        _hop("jev"), _hop("openai"),
    ]))
    attempts = []
    records = []

    def call(hop, state, questions, *, timeout):
        attempts.append(hop.id)
        if hop.id == "jev":
            return {"answers": {"severity": {"type": "score", "score": 2}}}
        return {"answers": [{"name": "severity", "type": "score", "score": 1, "confidence": 0.8}]}

    monkeypatch.setattr(router, "_call_provider", call)
    monkeypatch.setattr(router, "_record_hop", lambda **kwargs: records.append(kwargs))

    result = router.decide(
        "state", {"severity": {"type": "score", "criteria": ["low", "high"]}},
        timeout=1, purpose="test",
    )

    assert attempts == ["jev", "openai"]
    assert records[0]["status"] == "invalid_response"
    assert result.answers["severity"]["score"] == 1.0


def test_provider_http_transport_enforces_wall_clock_deadline():
    async def slow_response(_request):
        await asyncio.sleep(0.2)
        return httpx.Response(200, json={"ok": True})

    client = router._WallClockHttpClient(httpx.MockTransport(slow_response))
    started = monotonic()

    with pytest.raises(httpx.ReadTimeout, match="wall-clock deadline"):
        client.get("https://provider.test/decision", timeout=0.02)

    assert monotonic() - started < 0.15


def test_runtime_configuration_rejects_arbitrary_endpoint():
    body = {"order": ["clef-primary"], "providers": [{
        "id": "clef-primary", "provider": "clef", "endpoint": "https://example.invalid",
        "model": "clef-flash", "api_key": "", "credential_required": False,
    }]}

    with pytest.raises(router.DecisionProviderError):
        router._parse_runtime_configuration(body)


def test_clef_request_uses_fixed_endpoint_model_and_bearer_key(monkeypatch):
    request = httpx.Request("POST", "https://clef.create360.ai/v1/systemone")
    response = httpx.Response(200, request=request, json={"answers": {}})
    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return response

    monkeypatch.setattr(router._HTTP, "post", post)
    hop = _hop("clef-primary", api_key="clef-secret")

    body = router._call_provider(hop, "state", {"q": {"type": "noul"}}, timeout=0.4)

    assert body == {"answers": {}}
    assert captured["url"] == "https://clef.create360.ai/v1/systemone"
    assert captured["json"]["model"] == "clef-flash"
    assert captured["headers"]["Authorization"] == "Bearer clef-secret"
    assert captured["timeout"] == 0.4


def test_runtime_config_fetch_uses_internal_auth_and_preserves_endpoint_order(monkeypatch):
    body = {"order": ["openai", "jev"], "providers": [
        {"id": "openai", "provider": "openai", "endpoint": _hop("openai").endpoint,
         "model": "gpt-6-luna", "api_key": "key", "credential_required": True},
        {"id": "jev", "provider": "jev", "endpoint": "https://jev.example/v1/systemone",
         "model": "jev-latest", "api_key": "jev-key", "credential_required": True},
    ]}
    response = httpx.Response(200, request=httpx.Request("GET", "http://backend"), json=body)
    captured = {}
    monkeypatch.setattr(router, "get_settings", lambda: type("Settings", (), {
        "gateway_internal_token": "internal-secret", "gateway_base_url": "http://backend:8200",
    })())

    def get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return response

    monkeypatch.setattr(router._HTTP, "get", get)

    result = router._fetch_provider_configuration(timeout=0.3)

    assert [hop.id for hop in result.providers] == ["openai", "jev"]
    assert result.providers[1].endpoint == "https://jev.example/v1/systemone"
    assert captured["url"] == "http://backend:8200/api/v1/internal/decision-providers"
    assert captured["headers"]["X-Internal-Token"] == "internal-secret"


def test_provider_usage_tracks_hop_and_never_includes_decision_input(monkeypatch):
    recorded = []
    monkeypatch.setattr("infra.usage_ledger.record_usage_event", lambda **kwargs: recorded.append(kwargs))

    router._record_hop(
        provider="clef", hop_id="clef-primary", model="clef-flash",
        purpose="memory_gate", elapsed_ms=42, status="ok",
        usage_obj={"input_tokens": 17, "output_tokens": 2},
    )

    [event] = recorded
    assert event["provider"] == "clef"
    assert event["kind"] == "decision_memory_gate"
    assert event["usage"].total_tokens == 19
    assert event["raw"] == {"hop_id": "clef-primary", "status": "ok"}


def test_runtime_order_and_provider_fallback_work_end_to_end_with_mocked_services(monkeypatch):
    providers = [
        {"id": hop_id, "provider": expected[0], "endpoint": expected[1],
         "model": expected[2], "api_key": "", "credential_required": expected[3]}
        for hop_id, expected in router._EXPECTED_HOPS.items()
    ]
    runtime_config = {"order": list(router._DEFAULT_ORDER), "providers": providers}
    attempts = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "backend":
            assert request.headers["X-Internal-Token"] == "internal-secret"
            return httpx.Response(200, json=runtime_config)
        attempts.append(str(request.url))
        if request.url.host == "clef.create360.ai":
            return httpx.Response(503, json={"detail": "unavailable"})
        if request.url.host == "clef.aiurl.tw":
            return httpx.Response(200, json={
                "model": "clef-flash",
                "answers": {"q": {"type": "noul", "noul": 0.91}},
                "usage": {"input_tokens": 20, "output_tokens": 2},
            })
        raise AssertionError(f"unexpected endpoint: {request.url}")

    monkeypatch.setattr(router, "get_settings", lambda: type("Settings", (), {
        "gateway_internal_token": "internal-secret", "gateway_base_url": "http://backend:8200",
    })())
    monkeypatch.setattr(router, "_HTTP", httpx.Client(transport=httpx.MockTransport(handle)))
    usage = []
    monkeypatch.setattr("infra.usage_ledger.record_usage_event", lambda **kwargs: usage.append(kwargs))
    router.clear_provider_configuration_cache()

    result = router.decide("sample state", {"q": {"type": "noul"}}, timeout=1, purpose="integration")

    assert result.hop_id == "clef-backup"
    assert result.answers["q"]["noul"] == 0.91
    assert [url.split("/")[2] for url in attempts] == ["clef.create360.ai", "clef.aiurl.tw"]
    assert [event["raw"]["hop_id"] for event in usage] == ["clef-primary", "clef-backup"]

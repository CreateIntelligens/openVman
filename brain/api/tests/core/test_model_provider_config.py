from __future__ import annotations

import httpx
import pytest

from core import model_provider_config as config


def _settings(token="internal-secret", base="http://backend:8200/"):
    return type("Settings", (), {"gateway_internal_token": token, "gateway_base_url": base})()


def test_fetch_section_calls_backend_with_internal_token(monkeypatch):
    monkeypatch.setattr(config, "get_settings", _settings)
    captured = {}

    def get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(
            200, request=httpx.Request("GET", url),
            json={"decision": {"order": []}, "chat_llm": {"configured": False}},
        )

    section = config.fetch_section("chat_llm", timeout=0.5, get=get)

    assert section == {"configured": False}
    assert captured["url"] == "http://backend:8200/api/v1/internal/model-providers"
    assert captured["headers"] == {"X-Internal-Token": "internal-secret"}
    assert captured["timeout"] == 0.5


def test_fetch_section_without_internal_token_fails_without_network(monkeypatch):
    monkeypatch.setattr(config, "get_settings", lambda: _settings(token=""))

    with pytest.raises(config.ModelProviderConfigUnavailable):
        config.fetch_section("chat_llm", timeout=0.5, get=lambda *a, **kw: pytest.fail("no request"))


def test_refreshing_value_caches_until_ttl_then_keeps_last_good_on_failure():
    value = config.RefreshingValue[str](ttl=60)
    assert value.get(lambda: "first") == "first"
    assert value.get(lambda: pytest.fail("still fresh")) == "first"

    value.ttl = 0

    def offline():
        raise ConnectionError("down")

    assert value.get(offline) == "first"
    assert value.get(lambda: "second") == "second"


def test_refreshing_value_without_history_raises_or_caches_default():
    def offline():
        raise ConnectionError("down")

    strict = config.RefreshingValue[str](ttl=60)
    with pytest.raises(ConnectionError):
        strict.get(offline)

    lenient = config.RefreshingValue[str | None](ttl=60)
    assert lenient.get(offline, default=None) is None
    assert lenient.get(lambda: pytest.fail("default is cached for one interval")) is None


def test_propagated_errors_bypass_the_cached_value():
    value = config.RefreshingValue[str](ttl=0)
    value.get(lambda: "first")

    class Cancelled(RuntimeError):
        pass

    def cancelled():
        raise Cancelled

    with pytest.raises(Cancelled):
        value.get(cancelled, propagate=(Cancelled,))

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


def test_threads_asking_at_once_load_only_once():
    import threading
    import time

    value = config.RefreshingValue(ttl=60)
    loads = []
    gate = threading.Barrier(20)

    def load():
        loads.append(1)
        time.sleep(0.2)
        return "doc"

    results = []

    def ask():
        gate.wait()
        results.append(value.get(load))

    threads = [threading.Thread(target=ask) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert loads == [1]
    assert results == ["doc"] * 20


def test_a_stale_value_is_served_while_one_thread_refreshes(monkeypatch):
    import threading

    clock = [100.0]
    monkeypatch.setattr(config, "monotonic", lambda: clock[0])
    value = config.RefreshingValue(ttl=10)
    assert value.get(lambda: "old") == "old"
    clock[0] += 11

    started = threading.Event()
    release = threading.Event()

    def slow_load():
        started.set()
        release.wait(2)
        return "new"

    refresher = threading.Thread(target=lambda: value.get(slow_load))
    refresher.start()
    assert started.wait(2)

    assert value.get(lambda: "should not load") == "old"

    release.set()
    refresher.join()
    assert value.get(lambda: "should not load") == "new"

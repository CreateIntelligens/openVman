from __future__ import annotations

import threading
import time
import json
from pathlib import Path

import pytest

from core.two_md import (
    RedisCoordination,
    TWO_MD_BASE_URLS,
    SingleFlight,
    build_operation_key,
    full_jitter_delay,
    resolve_base_urls,
)


def test_two_md_base_urls_are_canonical_and_immutable():
    assert TWO_MD_BASE_URLS == (
        "https://2md.aiurl.tw",
        "https://2md.glsoft.ai",
        "https://create360.ai",
    )
    with pytest.raises(TypeError):
        TWO_MD_BASE_URLS[0] = "https://unexpected.invalid"  # type: ignore[index]

    source = Path(__file__).resolve().parents[3] / "contracts" / "two-md-endpoints.json"
    assert tuple(json.loads(source.read_text())["base_urls"]) == TWO_MD_BASE_URLS


def test_resolve_base_urls_prefers_complete_override_and_validates_it():
    class Settings:
        url2md_base_urls = "https://first.example, https://first.example, https://second.example/"
        url2md_primary_url = "https://legacy.example"
        url2md_fallback_urls = "https://legacy-fallback.example"

    assert resolve_base_urls(Settings()) == (
        "https://first.example",
        "https://second.example",
    )

    class InvalidSettings:
        url2md_base_urls = "http://user:password@example.com/path"

    with pytest.raises(ValueError):
        resolve_base_urls(InvalidSettings())


def test_operation_key_normalizes_equivalent_inputs_without_mixing_scopes():
    first = build_operation_key(
        "search",
        {"query": "  OpenVman  ", "top_k": 8},
        response_policy="json:3000",
        privacy_scope="project-a",
    )
    equivalent = build_operation_key(
        "search",
        {"query": "OpenVman", "top_k": 8},
        response_policy="json:3000",
        privacy_scope="project-a",
    )
    other_scope = build_operation_key(
        "search",
        {"query": "OpenVman", "top_k": 8},
        response_policy="json:3000",
        privacy_scope="project-b",
    )

    assert first == equivalent
    assert first != other_scope


def test_singleflight_shares_one_inflight_result():
    flight = SingleFlight()
    started = threading.Event()
    release = threading.Event()
    calls = 0
    results: list[dict[str, str]] = []

    def operation():
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(1)
        return {"content": "shared"}

    def invoke():
        results.append(flight.run("same", operation, timeout_s=2))

    leader = threading.Thread(target=invoke)
    leader.start()
    assert started.wait(1)
    followers = [threading.Thread(target=invoke) for _ in range(3)]
    for thread in followers:
        thread.start()
    time.sleep(0.02)
    release.set()
    leader.join()
    for thread in followers:
        thread.join()

    assert calls == 1
    assert results == [{"content": "shared"}] * 4


def test_full_jitter_delay_is_bounded_by_remaining_budget():
    assert full_jitter_delay(1, base_s=1.0, max_s=10.0, remaining_s=0.2, random_value=1.0) == 0.2
    assert full_jitter_delay(3, base_s=1.0, max_s=10.0, remaining_s=4.0, random_value=0.5) == 2.0


class _FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}

    def exists(self, key):
        return int(key in self.values)

    def set(self, key, value, nx=False, px=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, key):
        self.values.pop(key, None)
        return 1

    def eval(self, script, count, key, token):
        if self.values.get(key) == token:
            self.values.pop(key, None)
            return 1
        return 0


def test_redis_coordination_allows_only_one_half_open_probe():
    redis = _FakeRedis()
    first = RedisCoordination("redis://unused", client=redis)
    second = RedisCoordination("redis://unused", client=redis)
    endpoint = "https://2md.aiurl.tw"
    first.mark_failure(endpoint, cooldown_s=60)

    assert first.endpoint_allowed(endpoint, cooldown_s=60, lease_s=5) is False
    redis.values.pop(first._key("circuit", endpoint))
    assert first.endpoint_allowed(endpoint, cooldown_s=60, lease_s=5) is True
    assert second.endpoint_allowed(endpoint, cooldown_s=60, lease_s=5) is False

    first.mark_success(endpoint)
    assert second.endpoint_allowed(endpoint, cooldown_s=60, lease_s=5) is True


def test_redis_coordination_falls_back_when_backend_becomes_unavailable():
    class BrokenRedis:
        def exists(self, key):
            raise ConnectionError("redis unavailable")

    coordination = RedisCoordination("redis://unused", client=BrokenRedis())

    assert coordination.endpoint_allowed("https://2md.aiurl.tw", cooldown_s=60, lease_s=5) is True
    assert coordination.configured is False

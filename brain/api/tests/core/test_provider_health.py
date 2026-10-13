from __future__ import annotations

from core.provider_health import HopId, ProviderHealth, key_fingerprint


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _hop(name: str, key: str = "k") -> HopId:
    return HopId.of("chat_llm", name, "m", key)


def _order(health: ProviderHealth, *names: str) -> list[str]:
    return [hop.hop for hop in health.order([_hop(name) for name in names], lambda hop: hop)]


def test_invalid_key_moves_behind_healthy_hops_until_the_key_changes():
    health = ProviderHealth(clock=Clock())
    health.record_failure(_hop("gemini"), "auth", "auth_invalid")

    assert _order(health, "gemini", "openai") == ["openai", "gemini"]
    fresh_key = [_hop("gemini", "new-key"), _hop("openai")]
    assert health.order(fresh_key, lambda hop: hop)[0] == _hop("gemini", "new-key")


def test_one_transient_failure_does_not_reorder_but_two_cool_for_a_minute():
    clock = Clock()
    health = ProviderHealth(clock=clock)

    health.record_failure(_hop("gemini"), "transient", "timeout")
    assert _order(health, "gemini", "openai") == ["gemini", "openai"]

    health.record_failure(_hop("gemini"), "transient", "timeout")
    assert _order(health, "gemini", "openai") == ["openai", "gemini"]

    clock.now += 61
    assert _order(health, "gemini", "openai") == ["gemini", "openai"]


def test_quota_cools_for_five_minutes_and_success_clears_it():
    clock = Clock()
    health = ProviderHealth(clock=clock)
    health.record_failure(_hop("groq"), "quota", "quota_exhausted")

    clock.now += 299
    assert _order(health, "groq", "nen") == ["nen", "groq"]
    health.record_success(_hop("groq"))
    assert _order(health, "groq", "nen") == ["groq", "nen"]


def test_nothing_is_dropped_and_cooling_hops_run_before_blocked_ones():
    health = ProviderHealth(clock=Clock())
    health.record_failure(_hop("a"), "auth", "auth_invalid")
    health.record_failure(_hop("b"), "quota", "quota_exhausted")

    assert _order(health, "a", "b") == ["b", "a"]


def test_snapshot_reports_failing_hops_without_the_key():
    health = ProviderHealth(clock=Clock())
    health.record_failure(_hop("gemini", "secret-key"), "auth", "auth_invalid")

    [entry] = health.snapshot()
    assert entry["status"] == "blocked"
    assert entry["key_fingerprint"] == key_fingerprint("secret-key")
    assert "secret-key" not in str(entry)


def test_reset_clears_one_hop_or_everything():
    health = ProviderHealth(clock=Clock())
    health.record_failure(_hop("gemini"), "auth", "auth_invalid")
    health.record_failure(_hop("groq"), "quota", "quota_exhausted")

    assert health.reset(category="chat_llm", hop="gemini") == 1
    assert [entry["hop"] for entry in health.snapshot()] == ["groq"]
    assert health.reset() == 1
    assert health.snapshot() == []

"""Tests for Privacy Filter LRU cache."""

from __future__ import annotations

from privacy.cache import PrivacyFilterCache


def test_cache_hit_returns_cached_value() -> None:
    cache = PrivacyFilterCache(max_entries=2)
    cache.set("hello@example.com", {"private_email": 1})

    assert cache.get("hello@example.com") == {"private_email": 1}


def test_cache_miss_returns_none() -> None:
    cache = PrivacyFilterCache(max_entries=2)

    assert cache.get("missing") is None


def test_cache_evicts_least_recently_used_entry() -> None:
    cache = PrivacyFilterCache(max_entries=2)
    cache.set("first", {})
    cache.set("second", {"private_email": 1})
    assert cache.get("first") == {}

    cache.set("third", {"private_phone": 1})

    assert cache.get("second") is None
    assert cache.get("first") == {}
    assert cache.get("third") == {"private_phone": 1}

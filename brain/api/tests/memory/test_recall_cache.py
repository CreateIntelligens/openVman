"""Tests for memory.recall_cache — TTL, FIFO eviction, and cache key."""

from __future__ import annotations

import time

import pytest

from memory.recall_cache import RecallCache, make_cache_key


@pytest.fixture()
def cache():
    return RecallCache(ttl_ms=200, max_entries=3)


# ------------------------------------------------------------------
# Cache hit / miss
# ------------------------------------------------------------------


def test_cache_hit(cache: RecallCache):
    cache.set("k1", "hello")
    assert cache.get("k1") == "hello"


def test_cache_miss(cache: RecallCache):
    assert cache.get("nonexistent") is None


# ------------------------------------------------------------------
# TTL expiry
# ------------------------------------------------------------------


def test_ttl_expiry(cache: RecallCache):
    cache.set("k1", "hello")
    time.sleep(0.25)
    assert cache.get("k1") is None


def test_ttl_not_expired(cache: RecallCache):
    cache.set("k1", "hello")
    time.sleep(0.05)
    assert cache.get("k1") == "hello"


# ------------------------------------------------------------------
# FIFO eviction
# ------------------------------------------------------------------


def test_fifo_eviction(cache: RecallCache):
    """Oldest entry evicted when max entries exceeded."""
    cache.set("a", "1")
    cache.set("b", "2")
    cache.set("c", "3")
    cache.set("d", "4")  # should evict "a"
    assert cache.get("a") is None
    assert cache.get("b") == "2"
    assert cache.get("d") == "4"


def test_overwrite_existing_key(cache: RecallCache):
    cache.set("k1", "old")
    cache.set("k1", "new")
    assert cache.get("k1") == "new"


# ------------------------------------------------------------------
# sweep_expired
# ------------------------------------------------------------------


def test_sweep_expired(cache: RecallCache):
    cache.set("k1", "hello")
    cache.set("k2", "world")
    time.sleep(0.25)
    removed = cache.sweep_expired()
    assert removed == 2
    assert cache.get("k1") is None
    assert cache.get("k2") is None


def test_sweep_keeps_valid(cache: RecallCache):
    cache.set("k1", "hello")
    removed = cache.sweep_expired()
    assert removed == 0
    assert cache.get("k1") == "hello"


# ------------------------------------------------------------------
# Cache key
# ------------------------------------------------------------------


def test_cache_key_deterministic():
    k1 = make_cache_key("sess1", "query text")
    k2 = make_cache_key("sess1", "query text")
    assert k1 == k2


def test_cache_key_differs_by_session():
    k1 = make_cache_key("sess1", "query text")
    k2 = make_cache_key("sess2", "query text")
    assert k1 != k2


def test_cache_key_differs_by_query():
    k1 = make_cache_key("sess1", "query a")
    k2 = make_cache_key("sess1", "query b")
    assert k1 != k2

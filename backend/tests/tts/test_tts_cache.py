"""Tests for the Redis-backed TTS cache helpers."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tts_cache import CachedTTSEntry, cache_get, cache_put, make_cache_key


class TestMakeCacheKey:
    def test_is_deterministic(self):
        assert make_cache_key("hello", "hayley", "indextts") == make_cache_key(
            "hello", "hayley", "indextts",
        )

    def test_changes_when_input_changes(self):
        assert make_cache_key("hello", "hayley", "indextts") != make_cache_key(
            "hello!", "hayley", "indextts",
        )
        assert make_cache_key("hello", "hayley", "indextts") != make_cache_key(
            "hello", "jay", "indextts",
        )
        assert make_cache_key("hello", "hayley", "indextts") != make_cache_key(
            "hello", "hayley", "edge-tts",
        )

    def test_matches_expected_sha256_format(self):
        expected = hashlib.sha256("hello|hayley|indextts".encode("utf-8")).hexdigest()
        assert make_cache_key("hello", "hayley", "indextts") == f"tts:v1:{expected}"


@pytest.mark.asyncio
async def test_cache_get_returns_none_when_redis_unavailable():
    with patch("app.tts_cache.get_redis", AsyncMock(return_value=None)):
        assert await cache_get("tts:v1:test") is None


@pytest.mark.asyncio
async def test_cache_get_returns_none_on_miss():
    redis = MagicMock()
    redis.hgetall = AsyncMock(return_value={})

    with patch("app.tts_cache.get_redis", AsyncMock(return_value=redis)):
        assert await cache_get("tts:v1:test") is None


@pytest.mark.asyncio
async def test_cache_get_returns_cached_entry_on_hit():
    redis = MagicMock()
    redis.hgetall = AsyncMock(return_value={
        b"audio_bytes": b"audio-data",
        b"content_type": b"audio/wav",
        b"provider": b"indextts",
        b"route_kind": b"provider",
        b"route_target": b"indextts",
        b"sample_rate": b"16000",
    })

    with patch("app.tts_cache.get_redis", AsyncMock(return_value=redis)):
        entry = await cache_get("tts:v1:test")

    assert entry == CachedTTSEntry(
        audio_bytes=b"audio-data",
        content_type="audio/wav",
        provider="indextts",
        route_kind="provider",
        route_target="indextts",
        sample_rate=16000,
    )


@pytest.mark.asyncio
async def test_cache_get_returns_none_when_redis_errors():
    redis = MagicMock()
    redis.hgetall = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("app.tts_cache.get_redis", AsyncMock(return_value=redis)):
        assert await cache_get("tts:v1:test") is None


@pytest.mark.asyncio
async def test_cache_put_is_noop_when_redis_unavailable():
    entry = CachedTTSEntry(
        audio_bytes=b"audio-data",
        content_type="audio/wav",
        provider="indextts",
        route_kind="provider",
        route_target="indextts",
        sample_rate=16000,
    )

    with patch("app.tts_cache.get_redis", AsyncMock(return_value=None)):
        assert await cache_put("tts:v1:test", entry, 123) is None


@pytest.mark.asyncio
async def test_cache_put_writes_hash_and_ttl():
    entry = CachedTTSEntry(
        audio_bytes=b"audio-data",
        content_type="audio/wav",
        provider="indextts",
        route_kind="provider",
        route_target="indextts",
        sample_rate=16000,
    )
    pipe = MagicMock()
    pipe.hset.return_value = pipe
    pipe.expire.return_value = pipe
    pipe.execute = AsyncMock(return_value=[1, True])
    redis = MagicMock()
    redis.pipeline.return_value = pipe

    with patch("app.tts_cache.get_redis", AsyncMock(return_value=redis)):
        await cache_put("tts:v1:test", entry, 123)

    pipe.hset.assert_called_once_with(
        "tts:v1:test",
        mapping={
            "audio_bytes": b"audio-data",
            "content_type": "audio/wav",
            "provider": "indextts",
            "route_kind": "provider",
            "route_target": "indextts",
            "sample_rate": "16000",
        },
    )
    pipe.expire.assert_called_once_with("tts:v1:test", 123)
    pipe.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_put_is_noop_when_redis_errors():
    entry = CachedTTSEntry(
        audio_bytes=b"audio-data",
        content_type="audio/wav",
        provider="indextts",
        route_kind="provider",
        route_target="indextts",
        sample_rate=16000,
    )
    pipe = MagicMock()
    pipe.hset.return_value = pipe
    pipe.expire.return_value = pipe
    pipe.execute = AsyncMock(side_effect=RuntimeError("boom"))
    redis = MagicMock()
    redis.pipeline.return_value = pipe

    with patch("app.tts_cache.get_redis", AsyncMock(return_value=redis)):
        assert await cache_put("tts:v1:test", entry, 123) is None

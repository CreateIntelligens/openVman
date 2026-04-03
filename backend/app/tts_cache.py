"""TTS Redis cache layer — async, gracefully degrades if Redis is unavailable."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from time import monotonic

from app.gateway.redis_pool import get_redis
from app.observability import (
    record_cache_error,
    record_cache_hit,
    record_cache_miss,
    record_cache_store,
)

_STRING_FIELDS = ("content_type", "provider", "route_kind", "route_target")
_REQUIRED_FIELDS = ("audio_bytes", *_STRING_FIELDS, "sample_rate")


@dataclass(frozen=True, slots=True)
class CachedTTSEntry:
    audio_bytes: bytes
    content_type: str
    provider: str
    route_kind: str
    route_target: str
    sample_rate: int


def make_cache_key(text: str, voice_hint: str, provider: str) -> str:
    """Return the Redis key for a TTS payload."""
    raw = f"{text}|{voice_hint}|{provider}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"tts:v1:{digest}"


def _decode_cache_payload(payload: dict[bytes, bytes]) -> CachedTTSEntry | None:
    decoded = {
        key.decode("utf-8"): value
        for key, value in payload.items()
        if isinstance(key, bytes)
    }

    if any(field not in decoded for field in _REQUIRED_FIELDS):
        missing = [field for field in _REQUIRED_FIELDS if field not in decoded]
        record_cache_error("get", f"missing_fields:{','.join(missing)}")
        return None

    try:
        return CachedTTSEntry(
            audio_bytes=decoded["audio_bytes"],
            content_type=decoded["content_type"].decode("utf-8"),
            provider=decoded["provider"].decode("utf-8"),
            route_kind=decoded["route_kind"].decode("utf-8"),
            route_target=decoded["route_target"].decode("utf-8"),
            sample_rate=int(decoded["sample_rate"].decode("utf-8")),
        )
    except Exception as exc:
        record_cache_error("get", f"decode_failed:{exc}")
        return None


def _to_redis_mapping(entry: CachedTTSEntry) -> dict[str, bytes | str]:
    return {
        "audio_bytes": entry.audio_bytes,
        "content_type": entry.content_type,
        "provider": entry.provider,
        "route_kind": entry.route_kind,
        "route_target": entry.route_target,
        "sample_rate": str(entry.sample_rate),
    }


async def cache_get(key: str) -> CachedTTSEntry | None:
    """Fetch an entry from Redis. Returns None on miss or error."""
    redis = await get_redis()
    if redis is None:
        return None

    t0 = monotonic()
    try:
        payload = await redis.hgetall(key)
    except Exception as exc:
        record_cache_error("get", str(exc))
        return None

    latency_ms = (monotonic() - t0) * 1000
    if not payload:
        record_cache_miss(latency_ms)
        return None

    entry = _decode_cache_payload(payload)
    if entry is None:
        return None

    record_cache_hit(latency_ms)
    return entry


async def cache_put(key: str, entry: CachedTTSEntry, ttl_seconds: int) -> None:
    """Store an entry in Redis. Errors are recorded and otherwise ignored."""
    redis = await get_redis()
    if redis is None:
        return None

    t0 = monotonic()
    try:
        pipe = redis.pipeline()
        pipe.hset(key, mapping=_to_redis_mapping(entry))
        pipe.expire(key, ttl_seconds)
        await pipe.execute()
    except Exception as exc:
        record_cache_error("put", str(exc))
        return None

    record_cache_store((monotonic() - t0) * 1000)
    return None

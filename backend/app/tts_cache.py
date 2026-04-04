"""TTS Redis cache layer — async, gracefully degrades if Redis is unavailable."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, fields
from time import monotonic

from app.gateway.redis_pool import get_redis
from typing import Literal

from app.observability import (
    record_cache_error,
    record_cache_hit,
    record_cache_miss,
    record_cache_store,
)

_STRING_FIELDS = ("content_type", "provider", "route_kind", "route_target")


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


def _record_error(op: Literal["get", "put"], detail: str) -> None:
    record_cache_error(op, detail)


def _decode_cache_payload(payload: dict[bytes, bytes]) -> CachedTTSEntry | None:
    decoded = {
        key.decode("utf-8"): value
        for key, value in payload.items()
        if isinstance(key, bytes)
    }

    expected = {f.name for f in fields(CachedTTSEntry)}
    missing = [f for f in expected if f not in decoded]
    if missing:
        _record_error("get", f"missing_fields:{','.join(sorted(missing))}")
        return None

    try:
        kwargs = {f: decoded[f].decode("utf-8") for f in _STRING_FIELDS}
        kwargs["audio_bytes"] = decoded["audio_bytes"]
        kwargs["sample_rate"] = int(decoded["sample_rate"].decode("utf-8"))
        return CachedTTSEntry(**kwargs)
    except Exception as exc:
        _record_error("get", f"decode_failed:{exc}")
        return None


def _to_redis_mapping(entry: CachedTTSEntry) -> dict[str, bytes | str]:
    return {
        f.name: (str(getattr(entry, f.name)) if f.type == "int" else getattr(entry, f.name))
        for f in fields(CachedTTSEntry)
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
        _record_error("get", str(exc))
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
        return

    t0 = monotonic()
    try:
        pipe = redis.pipeline()
        pipe.hset(key, mapping=_to_redis_mapping(entry))
        pipe.expire(key, ttl_seconds)
        await pipe.execute()
    except Exception as exc:
        _record_error("put", str(exc))
        return

    record_cache_store((monotonic() - t0) * 1000)

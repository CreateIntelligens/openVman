"""Redis connection singleton for the gateway."""

from __future__ import annotations

import logging

from app.config import get_tts_config

logger = logging.getLogger("gateway.redis")

try:
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover
    aioredis = None  # type: ignore[assignment]

_redis: aioredis.Redis | None = None  # type: ignore[name-defined]
_redis_failed: bool = False
_RETRY_AFTER: float = 30.0
_last_failure: float = 0.0


async def get_redis() -> aioredis.Redis | None:  # type: ignore[name-defined]
    global _redis, _redis_failed, _last_failure
    if aioredis is None:
        return None
    if _redis is not None:
        return _redis
    # Back off after a connection failure to avoid retrying on every request.
    if _redis_failed:
        from time import monotonic
        if (monotonic() - _last_failure) < _RETRY_AFTER:
            return None
        _redis_failed = False
    cfg = get_tts_config()
    try:
        _redis = aioredis.from_url(cfg.redis_url, decode_responses=False)
        await _redis.ping()
        logger.info("redis connected url=%s", cfg.redis_url)
        return _redis
    except Exception as exc:
        from time import monotonic
        logger.warning("redis connection failed: %s", exc)
        _redis = None
        _redis_failed = True
        _last_failure = monotonic()
        return None


async def redis_available() -> bool:
    r = await get_redis()
    if r is None:
        return False
    try:
        await r.ping()
        return True
    except Exception:
        return False


async def close_redis() -> None:
    global _redis, _redis_failed
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        _redis_failed = False
        logger.info("redis connection closed")

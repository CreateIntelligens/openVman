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


async def get_redis() -> aioredis.Redis | None:  # type: ignore[name-defined]
    global _redis
    if aioredis is None:
        return None
    if _redis is not None:
        return _redis
    cfg = get_tts_config()
    try:
        _redis = aioredis.from_url(cfg.redis_url, decode_responses=False)
        await _redis.ping()
        logger.info("redis connected url=%s", cfg.redis_url)
        return _redis
    except Exception as exc:
        logger.warning("redis connection failed: %s", exc)
        _redis = None
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
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("redis connection closed")

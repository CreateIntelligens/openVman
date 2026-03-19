"""Arq-based job queue with sync fallback."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from app.config import get_tts_config
from app.gateway.redis_pool import get_redis

logger = logging.getLogger("gateway.queue")

try:
    from arq import create_pool
    from arq.connections import ArqRedis, RedisSettings

    _HAS_ARQ = True
except ImportError:  # pragma: no cover
    _HAS_ARQ = False

_arq_pool: ArqRedis | None = None  # type: ignore[name-defined]


@dataclass(frozen=True)
class EnqueueResult:
    job_id: str
    mode: str  # "queued" | "sync"


async def _get_arq_pool() -> ArqRedis | None:  # type: ignore[name-defined]
    global _arq_pool
    if not _HAS_ARQ:
        return None
    if _arq_pool is not None:
        return _arq_pool

    redis = await get_redis()
    if redis is None:
        return None

    cfg = get_tts_config()
    try:
        _arq_pool = await create_pool(RedisSettings.from_dsn(cfg.redis_url))
        return _arq_pool
    except Exception as exc:
        logger.warning("arq pool creation failed: %s", exc)
        return None


SyncFallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


async def enqueue_job(
    job_name: str,
    data: dict[str, Any],
    *,
    sync_fallback: SyncFallback | None = None,
) -> EnqueueResult:
    job_id = uuid.uuid4().hex
    pool = await _get_arq_pool()

    if pool is not None:
        try:
            await pool.enqueue_job(job_name, data, _job_id=job_id)
            logger.info("job_enqueued job_id=%s job_name=%s", job_id, job_name)
            return EnqueueResult(job_id=job_id, mode="queued")
        except Exception as exc:
            logger.warning("arq enqueue failed, falling back to sync: %s", exc)

    # sync fallback
    if sync_fallback is not None:
        logger.info("job_sync_fallback job_id=%s job_name=%s", job_id, job_name)
        await sync_fallback({"__job_id": job_id, **data})
        return EnqueueResult(job_id=job_id, mode="sync")

    logger.warning("no queue and no sync fallback for job_name=%s", job_name)
    return EnqueueResult(job_id=job_id, mode="sync")


DLQ_KEY = "vman:gateway:dlq"
_DLQ_MAX_LEN = 1000


async def push_to_dlq(entry: dict[str, Any]) -> None:
    """Push a failed job entry to the dead-letter queue in Redis."""
    redis = await get_redis()
    if redis is None:
        logger.warning("dlq_push_skipped reason=no_redis entry=%s", entry)
        return

    try:
        await redis.lpush(DLQ_KEY, json.dumps(entry, default=str))
        await redis.ltrim(DLQ_KEY, 0, _DLQ_MAX_LEN - 1)
        logger.info("dlq_push job_name=%s trace_id=%s", entry.get("job_name"), entry.get("trace_id"))
    except Exception as exc:
        logger.error("dlq_push_failed err=%s", exc)


async def close_arq_pool() -> None:
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None

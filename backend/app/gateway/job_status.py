"""Job status storage for async gateway tasks."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.gateway.redis_pool import get_redis

logger = logging.getLogger("gateway.job_status")

JOB_STATUS_KEY_PREFIX = "vman:gateway:job:"
JOB_STATUS_TTL_SECONDS = 60 * 60

_memory_job_statuses: dict[str, dict[str, Any]] = {}


def _job_key(job_id: str) -> str:
    return f"{JOB_STATUS_KEY_PREFIX}{job_id}"


async def _read_from_redis(job_id: str) -> dict[str, Any] | None:
    redis = await get_redis()
    if redis is None:
        return None

    try:
        raw = await redis.get(_job_key(job_id))
    except Exception as exc:
        logger.warning("job_status_read_failed job_id=%s err=%s", job_id, exc)
        return None

    if raw is None:
        return None

    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        logger.warning("job_status_decode_failed job_id=%s err=%s", job_id, exc)
        return None

    if isinstance(payload, dict):
        return payload
    return None


async def get_job_status(job_id: str) -> dict[str, Any] | None:
    """Fetch the latest job status from Redis, falling back to memory."""
    payload = await _read_from_redis(job_id)
    if payload is not None:
        return payload

    cached = _memory_job_statuses.get(job_id)
    return dict(cached) if cached is not None else None


async def set_job_status(job_id: str, status: str, **fields: Any) -> dict[str, Any]:
    """Persist the latest job status in Redis, with in-memory fallback."""
    existing = await get_job_status(job_id) or {}
    payload = {
        **existing,
        **fields,
        "job_id": job_id,
        "status": status,
        "updated_at": int(time.time()),
    }

    _memory_job_statuses[job_id] = payload

    redis = await get_redis()
    if redis is None:
        return payload

    try:
        await redis.set(_job_key(job_id), json.dumps(payload, default=str), ex=JOB_STATUS_TTL_SECONDS)
    except Exception as exc:
        logger.warning("job_status_write_failed job_id=%s err=%s", job_id, exc)

    return payload


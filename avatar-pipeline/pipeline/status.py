"""Job status the backend reads to drive the admin UI and finalize bundles.

One JSON document per job in Redis under ``vman:avatar-pipeline:job:<id>``.
The backend owns the same key prefix (``app/avatar/jobs.py``); keep the
field names in step.
"""

from __future__ import annotations

import json
import time
from typing import Any

from redis.asyncio import Redis

JOB_KEY_PREFIX = "vman:avatar-pipeline:job:"
JOB_TTL_SECONDS = 24 * 60 * 60

STATE_QUEUED = "queued"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"


def job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


async def read_status(redis: Redis, job_id: str) -> dict[str, Any] | None:
    raw = await redis.get(job_key(job_id))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else None


async def write_status(redis: Redis, job_id: str, **fields: Any) -> dict[str, Any]:
    """Merge ``fields`` into the stored document and refresh its TTL."""
    current = await read_status(redis, job_id) or {"job_id": job_id}
    current.update(fields)
    current["updated_at"] = time.time()
    await redis.set(job_key(job_id), json.dumps(current), ex=JOB_TTL_SECONDS)
    return current

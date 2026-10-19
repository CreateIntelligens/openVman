"""arq worker: one ``build_avatar_bundle`` job at a time.

The backend enqueues ``{"job_id", "input_path", "output_dir"}`` on the
``vman:avatar-pipeline`` queue. The build runs as a subprocess so a MediaPipe
crash or a timeout only kills that job, not the worker, and so the event
loop stays free to relay progress.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections import deque
from pathlib import Path
from typing import Any

from arq.connections import RedisSettings
from redis.asyncio import Redis

from .status import (
    STATE_DONE,
    STATE_FAILED,
    STATE_RUNNING,
    write_status,
)

logger = logging.getLogger("avatar_pipeline.worker")

QUEUE_NAME = "vman:avatar-pipeline"
JOB_TIMEOUT_SECONDS = int(os.environ.get("AVATAR_PIPELINE_JOB_TIMEOUT", "1800"))
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")


def _parse_line(line: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


async def build_avatar_bundle(ctx: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    redis: Redis = ctx["status_redis"]
    job_id = str(data["job_id"])
    input_path = Path(data["input_path"])
    output_dir = Path(data["output_dir"])
    await write_status(redis, job_id, state=STATE_RUNNING, stage="prepare", done=0, total=0)

    cmd = [
        sys.executable, "-m", "pipeline.cli",
        "--input", str(input_path), "--output", str(output_dir),
    ]
    # stderr 併進 stdout：MediaPipe 每幀都往 stderr 吐警告，分開讀會把 64 KB
    # 的管線塞滿、子行程卡在寫入，這裡又卡在等 stdout。
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    final: dict[str, Any] | None = None
    noise: deque[str] = deque(maxlen=20)
    last_reported = 0.0
    loop = asyncio.get_running_loop()
    async for line in proc.stdout:
        event = _parse_line(line)
        if event is None:
            text = line.decode("utf-8", errors="ignore").strip()
            if text:
                noise.append(text)
            continue
        if event.get("stage") in (STATE_DONE, STATE_FAILED):
            final = event
            continue
        # Frame-level progress arrives 25 times a second; the UI polls once a
        # second, so throttle the Redis writes.
        now = loop.time()
        if now - last_reported >= 0.5 or event.get("done") == event.get("total"):
            last_reported = now
            await write_status(
                redis, job_id,
                stage=event.get("stage"), done=event.get("done", 0), total=event.get("total", 0),
            )
    code = await proc.wait()

    if code != 0 or final is None or final.get("stage") != STATE_DONE:
        error = (final or {}).get("error") or "\n".join(noise)[-500:] or f"exit code {code}"
        logger.error("job_failed job_id=%s error=%s", job_id, error)
        await write_status(redis, job_id, state=STATE_FAILED, error=error)
        return {"job_id": job_id, "state": STATE_FAILED, "error": error}

    logger.info("job_done job_id=%s frames=%s", job_id, final.get("frame_count"))
    await write_status(
        redis, job_id,
        state=STATE_DONE, stage=STATE_DONE,
        frame_count=final.get("frame_count"),
        width=final.get("width"), height=final.get("height"),
    )
    return {"job_id": job_id, "state": STATE_DONE}


async def startup(ctx: dict[str, Any]) -> None:
    ctx["status_redis"] = Redis.from_url(REDIS_URL)


async def shutdown(ctx: dict[str, Any]) -> None:
    redis: Redis | None = ctx.get("status_redis")
    if redis is not None:
        await redis.aclose()


class WorkerSettings:
    functions = [build_avatar_bundle]
    queue_name = QUEUE_NAME
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    on_startup = startup
    on_shutdown = shutdown
    # MediaPipe saturates the CPUs on its own; a second job would only slow both.
    max_jobs = 1
    job_timeout = JOB_TIMEOUT_SECONDS
    max_tries = 1

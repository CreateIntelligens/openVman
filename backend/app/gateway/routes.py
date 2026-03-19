"""Gateway HTTP routes — upload, health, and admin endpoints."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import JSONResponse

from app.config import get_tts_config
from app.gateway.queue import DLQ_KEY, enqueue_job
from app.gateway.redis_pool import get_redis, redis_available
from app.gateway.temp_storage import get_temp_storage
from app.gateway.worker import process_media

logger = logging.getLogger("gateway.routes")
router = APIRouter()

_UPLOAD_CHUNK_SIZE = 1024 * 1024


async def _process_media_sync(data: dict[str, Any]) -> None:
    """Sync fallback: run process_media in-process when no queue is available."""
    await process_media({}, data)


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    session_id: str = Query(...),
) -> JSONResponse:
    cfg = get_tts_config()
    storage = get_temp_storage()
    trace_id = uuid.uuid4().hex

    # 1. quota check
    quota = storage.check_quota()
    if not quota.ok:
        return JSONResponse(
            status_code=413,
            content={"error": "storage_quota_exceeded", "usage_mb": quota.usage_mb, "limit_mb": quota.limit_mb},
        )

    # 2. MIME check
    mime_type = file.content_type or "application/octet-stream"
    if mime_type not in cfg.supported_mime_types:
        return JSONResponse(
            status_code=400,
            content={"error": "unsupported_mime_type", "mime_type": mime_type},
        )

    # 3. read file + size check
    chunks: list[bytes] = []
    total_size = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        chunks.append(chunk)
        total_size += len(chunk)

    if not storage.validate_file_size(total_size):
        return JSONResponse(
            status_code=413,
            content={"error": "file_too_large", "size_bytes": total_size},
        )

    # 4. write to temp storage
    data = b"".join(chunks)
    try:
        file_path = storage.write_file(session_id, data, mime_type)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    # 5. enqueue job
    job_data = {
        "file_path": file_path,
        "mime_type": mime_type,
        "session_id": session_id,
        "trace_id": trace_id,
    }

    result = await enqueue_job("process_media", job_data, sync_fallback=_process_media_sync)

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "job_id": result.job_id,
            "mode": result.mode,
            "session_id": session_id,
            "trace_id": trace_id,
        },
    )


@router.get("/health")
async def health() -> JSONResponse:
    storage = get_temp_storage()
    quota = storage.check_quota()
    is_redis_up = await redis_available()

    overall = "ok" if is_redis_up else "degraded"

    return JSONResponse(content={
        "status": overall,
        "service": "openVman-backend",
        "redis": "connected" if is_redis_up else "disconnected",
        "temp_storage": {
            "usage_mb": round(quota.usage_mb, 2),
            "limit_mb": quota.limit_mb,
            "ok": quota.ok,
        },
    })


@router.get("/admin/queue/dlq")
async def get_dlq(limit: int = Query(default=20, ge=1, le=100)) -> JSONResponse:
    """Return dead-letter queue entries from Redis."""
    redis = await get_redis()
    if redis is None:
        return JSONResponse(
            status_code=503,
            content={"error": "redis_unavailable"},
        )

    try:
        raw_entries = await redis.lrange(DLQ_KEY, 0, limit - 1)
        entries = []
        for raw in raw_entries:
            try:
                entries.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                entries.append({"raw": text})

        return JSONResponse(content={"count": len(entries), "entries": entries})
    except Exception as exc:
        logger.error("dlq_read_error err=%s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})

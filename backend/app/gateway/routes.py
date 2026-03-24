"""Gateway HTTP routes — upload, health, and admin endpoints."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any
from urllib.parse import urlparse as parse_url

import httpx
from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.brain_proxy import _http as _brain_http
from app.config import get_tts_config
from app.error_payloads import upload_failed_response
from app.gateway.crawl_adapter import CrawlResult, fetch_page
from app.gateway.job_status import get_job_status, set_job_status
from app.gateway.queue import DLQ_KEY, enqueue_job
from app.gateway.redis_pool import get_redis
from app.gateway.temp_storage import get_temp_storage
from app.gateway.worker import process_media

logger = logging.getLogger("gateway.routes")
router = APIRouter()

_UPLOAD_CHUNK_SIZE = 1024 * 1024


async def _process_media_sync(data: dict[str, Any]) -> None:
    """Sync fallback: run process_media in-process when no queue is available."""
    await process_media({}, data)


def _error_response(status_code: int, error: str, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error, **extra})


def _build_crawl_markdown(title: str, source_url: str, content: str) -> bytes:
    return f"# {title}\n\nSource: {source_url}\n\n{content}".encode("utf-8")


def _build_crawl_filename(source_url: str) -> str:
    parsed_url = parse_url(source_url)
    slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", f"{parsed_url.netloc}{parsed_url.path}")
    return f"{slug.strip('_')[:120]}.md"


async def _sync_crawled_document_meta(
    client: httpx.AsyncClient,
    brain_url: str,
    path: str,
    project_id: str,
    source_url: str,
) -> None:
    response = await client.patch(
        f"{brain_url}/brain/knowledge/document/meta",
        json={
            "path": path,
            "project_id": project_id,
            "source_type": "web",
            "source_url": source_url,
            "enabled": True,
        },
    )
    response.raise_for_status()


@router.post("/uploads", tags=["Uploads"])
async def upload(
    file: UploadFile = File(...),
    session_id: str = Query(...),
) -> JSONResponse:
    cfg = get_tts_config()
    storage = get_temp_storage()
    job_id = uuid.uuid4().hex
    trace_id = uuid.uuid4().hex

    # 1. quota check
    quota = storage.check_quota()
    if not quota.ok:
        return upload_failed_response(
            status_code=413,
            error="storage_quota_exceeded",
            usage_mb=quota.usage_mb,
            limit_mb=quota.limit_mb,
        )

    # 2. MIME check
    mime_type = file.content_type or "application/octet-stream"
    if mime_type not in cfg.supported_mime_types:
        return upload_failed_response(
            status_code=400,
            error="unsupported_mime_type",
            mime_type=mime_type,
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
        return upload_failed_response(
            status_code=413,
            error="file_too_large",
            size_bytes=total_size,
        )

    # 4. write to temp storage
    data = b"".join(chunks)
    try:
        file_path = storage.write_file(session_id, data, mime_type)
    except ValueError as exc:
        return upload_failed_response(
            status_code=400,
            error=str(exc),
        )

    # 5. enqueue job
    job_data = {
        "file_path": file_path,
        "mime_type": mime_type,
        "session_id": session_id,
        "trace_id": trace_id,
    }

    await set_job_status(
        job_id,
        "accepted",
        session_id=session_id,
        trace_id=trace_id,
    )

    result = await enqueue_job("process_media", job_data, job_id=job_id, sync_fallback=_process_media_sync)

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "job_id": result.job_id,
            "mode": result.mode,
            "session_id": session_id,
            "trace_id": trace_id,
            "status_url": f"/jobs/{result.job_id}",
        },
    )


@router.get("/jobs/{job_id}", tags=["Uploads"])
async def get_job(job_id: str) -> JSONResponse:
    payload = await get_job_status(job_id)
    if payload is None:
        return JSONResponse(status_code=404, content={"error": "job_not_found"})

    return JSONResponse(content=payload)



@router.get("/admin/dlq", tags=["Admin"])
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


# ---------------------------------------------------------------------------
# Knowledge: URL Crawl + Ingest
# ---------------------------------------------------------------------------

class CrawlIngestRequest(BaseModel):
    url: str = Field(..., min_length=1)
    project_id: str = "default"


async def _safe_fetch_page(url: str) -> CrawlResult | JSONResponse:
    """Fetch a page, returning CrawlResult on success or JSONResponse on error."""
    try:
        return await fetch_page(url)
    except ValueError as exc:
        return _error_response(400, str(exc))
    except httpx.TimeoutException:
        return _error_response(504, "抓取逾時", url=url)
    except httpx.HTTPStatusError as exc:
        return _error_response(502, f"網頁回傳錯誤：{exc.response.status_code}", url=url)
    except RuntimeError as exc:
        return _error_response(422, str(exc))


@router.post("/api/knowledge/crawl", tags=["Knowledge"])
async def crawl_and_ingest(req: CrawlIngestRequest) -> JSONResponse:
    """抓取網址內容並匯入知識庫。"""
    result = await _safe_fetch_page(req.url)
    if isinstance(result, JSONResponse):
        return result

    cfg = get_tts_config()
    client = _brain_http.get()
    file_bytes = _build_crawl_markdown(result.title, result.source_url, result.content)
    filename = _build_crawl_filename(result.source_url)

    try:
        resp = await client.post(
            f"{cfg.brain_url}/brain/knowledge/upload",
            files={"files": (filename, file_bytes, "text/markdown")},
            data={"target_dir": "knowledge/ingested", "project_id": req.project_id},
        )
        resp.raise_for_status()
        upload_result = resp.json()
    except httpx.HTTPError as exc:
        logger.error("crawl_upload_failed url=%s err=%s", req.url, exc)
        return _error_response(502, f"知識庫寫入失敗：{exc}", url=req.url)

    uploaded_files = upload_result.get("files") or []
    first = uploaded_files[0] if uploaded_files else None
    path = first.get("path", "") if first else ""
    size = first.get("size", 0) if first else len(file_bytes)

    if path:
        try:
            await _sync_crawled_document_meta(client, cfg.brain_url, path, req.project_id, result.source_url)
        except httpx.HTTPError as exc:
            logger.error("crawl_meta_sync_failed path=%s err=%s", path, exc)
            return _error_response(502, f"知識 metadata 寫入失敗：{exc}", path=path, url=req.url)

    return JSONResponse(content={
        "status": "ok",
        "title": result.title,
        "source_url": result.source_url,
        "path": path,
        "size": size,
    })


@router.post("/api/knowledge/fetch", tags=["Knowledge"])
async def fetch_web_content(req: CrawlIngestRequest) -> JSONResponse:
    """抓取網址內容但不存入知識庫，供 agent tool 即時查詢使用。"""
    result = await _safe_fetch_page(req.url)
    if isinstance(result, JSONResponse):
        return result

    return JSONResponse(content={
        "status": "ok",
        "title": result.title,
        "source_url": result.source_url,
        "content": result.content,
    })

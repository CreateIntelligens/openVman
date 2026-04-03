"""Gateway HTTP routes — upload, health, and admin endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.brain_proxy import _http as _brain_http
from app.config import get_tts_config
from app.error_payloads import upload_failed_response
from app.gateway.crawl_adapter import CrawlResult, fetch_page
from app.gateway.ingestion import IngestionResult, ingest_document
from app.gateway.ingestion_youtube import (
    YouTubeTranscriptError,
    fetch_transcript,
    is_youtube_url,
)
from app.gateway.job_status import get_job_status, set_job_status
from app.gateway.queue import DLQ_KEY, enqueue_job
from app.gateway.redis_pool import get_redis
from app.gateway.temp_storage import get_temp_storage
from app.gateway.worker import process_media
from app.utils.upload import UPLOAD_CHUNK_SIZE, UploadTooLargeError, cleanup_temp_path, persist_upload_to_tempfile

logger = logging.getLogger("gateway.routes")
router = APIRouter()

_KNOWLEDGE_PASSTHROUGH_SUFFIXES = frozenset({".md", ".txt", ".csv"})


async def _process_media_sync(data: dict[str, Any]) -> None:
    """Sync fallback: run process_media in-process when no queue is available."""
    await process_media({}, data)


async def _prepare_passthrough_upload(upload: UploadFile) -> tuple[str, bytes, str]:
    try:
        return (
            upload.filename or "",
            await upload.read(),
            upload.content_type or "application/octet-stream",
        )
    finally:
        await upload.close()


def _should_passthrough_knowledge_upload(upload: UploadFile) -> bool:
    return Path(upload.filename or "").suffix.lower() in _KNOWLEDGE_PASSTHROUGH_SUFFIXES


async def _prepare_document_upload(
    upload: UploadFile,
    *,
    cfg: Any,
    brain_client: httpx.AsyncClient,
    brain_url: str,
    markdown_target_dir: str,
    project_id: str,
    max_bytes: int,
) -> tuple[str, bytes, str]:
    suffix = Path(upload.filename or "").suffix
    safe_stem = Path(upload.filename or "document").stem or "document"
    trace_id = uuid.uuid4().hex
    tmp_path: str | None = None

    try:
        tmp_path, _ = await persist_upload_to_tempfile(
            upload,
            suffix=suffix,
            max_bytes=max_bytes,
        )
        await _upload_raw_artifact(
            brain_client,
            brain_url=brain_url,
            file_path=tmp_path,
            original_filename=upload.filename or Path(tmp_path).name,
            target_dir=markdown_target_dir,
            project_id=project_id,
        )
        result = await asyncio.to_thread(ingest_document, tmp_path, trace_id=trace_id, cfg=cfg)
        return (
            f"{safe_stem}.md",
            result.content.encode("utf-8"),
            "text/markdown",
        )
    finally:
        await upload.close()
        cleanup_temp_path(tmp_path)


def _build_raw_target_dir(target_dir: str) -> str:
    cleaned = target_dir.strip().strip("/")
    if not cleaned:
        return "raw"
        
    parts = cleaned.split("/")
    if parts[0] == "knowledge":
        parts = parts[1:]
        
    return "/".join(["raw", *parts]).rstrip("/") or "raw"


def _build_markdown_target_dir(target_dir: str) -> str:
    cleaned = target_dir.strip().strip("/")
    if not cleaned:
        return "knowledge/ingested"

    parts = cleaned.split("/")
    if parts[0] == "knowledge":
        return cleaned

    if parts[0] == "raw":
        parts = parts[1:]

    return "/".join(["knowledge", *parts]).rstrip("/") or "knowledge/ingested"


async def _upload_raw_artifact(
    client: httpx.AsyncClient,
    *,
    brain_url: str,
    file_path: str,
    original_filename: str,
    target_dir: str,
    project_id: str,
) -> None:
    raw_path = Path(file_path)
    response = await client.post(
        f"{brain_url}/brain/knowledge/raw/upload",
        files={
            "files": (
                Path(original_filename).name,
                raw_path.read_bytes(),
                "application/octet-stream",
            )
        },
        data={
            "target_dir": _build_raw_target_dir(target_dir),
            "project_id": project_id,
        },
    )
    response.raise_for_status()


def _relay_brain_response(resp: httpx.Response) -> Response:
    content_type = resp.headers.get("content-type", "")
    if "application/json" in content_type:
        return JSONResponse(status_code=resp.status_code, content=resp.json())
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=content_type or None,
    )


def _error_response(status_code: int, error: str, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error, **extra})


@router.post(
    "/uploads",
    tags=["Uploads"],
    summary="上傳檔案",
    description="上傳圖文、語音等檔案至暫存區，並排入背景處理隊列。\n\n**所需欄位**：\n- `file` (Form, UploadFile): 欲上傳的檔案\n- `session_id` (Query, str): 指派歸屬的 Session ID",
)
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
    while chunk := await file.read(UPLOAD_CHUNK_SIZE):
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


@router.get(
    "/jobs/{job_id}",
    tags=["Uploads"],
    summary="取得上傳進度",
    description="查詢上傳或非同步處理任務的狀態。\n\n**所需欄位**：\n- `job_id` (Path, str): 處理任務的 ID",
)
async def get_job(job_id: str) -> JSONResponse:
    payload = await get_job_status(job_id)
    if payload is None:
        return JSONResponse(status_code=404, content={"error": "job_not_found"})

    return JSONResponse(content=payload)



@router.get(
    "/admin/dlq",
    tags=["Admin"],
    summary="取得死信佇列",
    description="讀取因為錯誤而未被處理的任務清單 (DLQ)。\n\n**所需欄位**：\n- `limit` (Query, int, 預設 20): 最多顯示的數量限制",
)
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


class YouTubeIngestRequest(BaseModel):
    url: str = Field(..., min_length=1)
    project_id: str = "default"
    save_to_knowledge: bool = False
    target_dir: str = ""


async def _fetch_youtube_transcript(url: str) -> dict[str, Any] | JSONResponse:
    """Fetch YouTube transcript. Returns dict on success, JSONResponse on error."""
    trace_id = uuid.uuid4().hex
    try:
        result = await asyncio.to_thread(fetch_transcript, url, trace_id)
        return {
            "status": "ok",
            "title": result.title,
            "source_url": f"https://www.youtube.com/watch?v={result.video_id}",
            "language": result.language,
            "video_id": result.video_id,
            "content": result.content,
        }
    except ValueError as exc:
        return _error_response(400, str(exc))
    except YouTubeTranscriptError as exc:
        return _error_response(422, str(exc))
    except Exception as exc:
        logger.error("yt_transcript_failed url=%s err=%s", url, exc)
        return _error_response(500, f"YouTube 字幕擷取失敗: {exc}")


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



@router.post(
    "/api/knowledge/upload",
    tags=["Knowledge"],
    summary="上傳知識文件",
    description="上傳文件到知識庫。UTF-8 文字檔會直接轉發給 Brain；PDF / DOCX 會先在 Backend 轉成 Markdown，再交由 Brain 存檔與重整索引。\n\n**所需欄位 (Form)**：\n- `files` (Form, list[UploadFile]): 要上傳的檔案\n- `target_dir` (Form, str, 預設 ''): 目標資料夾\n- `project_id` (Form, str, 預設 'default'): 專案 ID",
)
async def upload_knowledge_documents(
    files: list[UploadFile] = File(...),
    target_dir: str = Form(""),
    project_id: str = Form("default"),
) -> Response:
    cfg = get_tts_config()
    client = _brain_http.get()

    try:
        markdown_target_dir = _build_markdown_target_dir(target_dir)
        forwarded_files: list[tuple[str, tuple[str, bytes, str]]] = []
        for upload in files:
            if _should_passthrough_knowledge_upload(upload):
                forwarded = await _prepare_passthrough_upload(upload)
            else:
                forwarded = await _prepare_document_upload(
                    upload,
                    cfg=cfg,
                    brain_client=client,
                    brain_url=cfg.brain_url,
                    markdown_target_dir=markdown_target_dir,
                    project_id=project_id,
                    max_bytes=cfg.markitdown_max_upload_bytes,
                )
            forwarded_files.append(("files", forwarded))

        resp = await client.post(
            f"{cfg.brain_url}/brain/knowledge/upload",
            files=forwarded_files,
            data={"target_dir": markdown_target_dir, "project_id": project_id},
        )
        return _relay_brain_response(resp)
    except UploadTooLargeError as exc:
        limit_mb = exc.limit_bytes / (1024 * 1024)
        return upload_failed_response(
            status_code=413,
            error=f"檔案超過大小限制（上限 {limit_mb:.0f} MB）",
        )
    except httpx.ConnectError:
        logger.warning("knowledge_upload_brain_unreachable target_dir=%s project_id=%s", target_dir, project_id)
        return _error_response(502, "brain service unavailable")
    except Exception as exc:
        logger.error("knowledge_upload_failed target_dir=%s project_id=%s err=%s", target_dir, project_id, exc)
        return upload_failed_response(
            status_code=500,
            error=str(exc),
        )


@router.post(
    "/api/knowledge/fetch",
    tags=["Knowledge"],
    summary="即時抓取頁面內容",
    description="抓取網址頁面內容並回傳，不存入知識庫。本端點供給 AI Tool 當作即時爬蟲功能使用。支援一般網頁及 YouTube 連結（自動擷取字幕）。\n\n**所需欄位**：\n- `url` (Body, str): 要抓取的網址\n- `project_id` (Body, str, 預設 'default'): 專案 ID",
)
async def fetch_web_content(req: CrawlIngestRequest) -> JSONResponse:
    """抓取網址內容但不存入知識庫，供 agent tool 即時查詢使用。"""
    if is_youtube_url(req.url):
        yt = await _fetch_youtube_transcript(req.url)
        return yt if isinstance(yt, JSONResponse) else JSONResponse(content=yt)

    result = await _safe_fetch_page(req.url)
    if isinstance(result, JSONResponse):
        return result

    return JSONResponse(content={
        "status": "ok",
        "title": result.title,
        "source_url": result.source_url,
        "content": result.content,
    })


@router.post(
    "/api/knowledge/youtube",
    tags=["Knowledge"],
    summary="擷取 YouTube 字幕",
    description="從 YouTube 影片擷取字幕文字，可選擇存入知識庫。\n\n**所需欄位**：\n- `url` (Body, str): YouTube 影片網址\n- `project_id` (Body, str, 預設 'default'): 專案 ID\n- `save_to_knowledge` (Body, bool, 預設 false): 是否存入知識庫\n- `target_dir` (Body, str, 預設 ''): 知識庫目標資料夾",
)
async def ingest_youtube_transcript(req: YouTubeIngestRequest) -> JSONResponse:
    """擷取 YouTube 字幕，可選存入知識庫。"""
    result = await _fetch_youtube_transcript(req.url)
    if isinstance(result, JSONResponse):
        return result

    if not req.save_to_knowledge:
        return JSONResponse(content=result)

    filename = f"{result['title']}.md"
    markdown_bytes = f"# {result['title']}\n\n{result['content']}".encode("utf-8")

    client = _brain_http.get()
    cfg = get_tts_config()
    target_dir = _build_markdown_target_dir(req.target_dir)

    try:
        resp = await client.post(
            f"{cfg.brain_url}/brain/knowledge/upload",
            files=[("files", (filename, markdown_bytes, "text/markdown"))],
            data={"target_dir": target_dir, "project_id": req.project_id},
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.error("yt_knowledge_upload_failed url=%s err=%s", req.url, exc)
        return _error_response(502, f"字幕擷取成功但存入知識庫失敗: {exc}")

    result["saved_to_knowledge"] = True
    result["target_dir"] = target_dir
    return JSONResponse(content=result)

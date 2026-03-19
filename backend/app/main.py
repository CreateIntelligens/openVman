"""openVman Backend — FastAPI entry point.

Serves TTS synthesis, MarkItDown document conversion, and gateway upload/queue.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from contextlib import suppress

from fastapi import FastAPI, File, Response, UploadFile
from fastapi.responses import JSONResponse
from markitdown import MarkItDown
from pydantic import BaseModel, Field

from app.config import get_tts_config
from app.gateway.redis_pool import close_redis, get_redis
from app.gateway.routes import router as gateway_router
from app.gateway.temp_storage import get_temp_storage, reset_temp_storage
from app.gateway.worker import (
    get_api_tool_plugin,
    get_camera_plugin,
    get_web_crawler_plugin,
    reset_plugins,
)
from app.observability import get_metrics_snapshot
from app.providers.base import SynthesizeRequest
from app.service import TTSRouterService

logger = logging.getLogger("backend")

app = FastAPI(title="openVman Backend")
_service: TTSRouterService | None = None
_md_converter: MarkItDown | None = None
_UPLOAD_CHUNK_SIZE = 1024 * 1024

# --- Gateway router ---
app.include_router(gateway_router)


@app.on_event("startup")
async def _startup() -> None:
    await _startup_gateway_resources()
    logger.info("backend startup complete")


@app.on_event("shutdown")
async def _shutdown() -> None:
    await _shutdown_gateway_resources()
    logger.info("backend shutdown complete")


def _get_service() -> TTSRouterService:
    global _service
    if _service is None:
        _service = TTSRouterService(get_tts_config())
    return _service


def _get_md_converter() -> MarkItDown:
    global _md_converter
    if _md_converter is None:
        _md_converter = MarkItDown()
    return _md_converter


async def _startup_gateway_resources() -> None:
    storage = get_temp_storage()
    await storage.start_cleanup_loop()
    await get_redis()
    get_camera_plugin()
    get_api_tool_plugin()
    get_web_crawler_plugin()


async def _shutdown_gateway_resources() -> None:
    storage = get_temp_storage()
    await storage.stop_cleanup_loop()
    from app.gateway.queue import close_arq_pool

    await close_arq_pool()
    await close_redis()
    reset_temp_storage()
    reset_plugins()


def _cleanup_temp_path(path: str | None) -> None:
    if path is None:
        return
    with suppress(FileNotFoundError):
        os.unlink(path)


class UploadTooLargeError(Exception):
    """Raised when an uploaded file exceeds the configured limit."""

    def __init__(self, limit_bytes: int) -> None:
        super().__init__(f"uploaded file too large: limit={limit_bytes}")
        self.limit_bytes = limit_bytes


async def _persist_upload_to_tempfile(
    file: UploadFile,
    *,
    suffix: str,
    max_bytes: int,
) -> tuple[str, int]:
    total_bytes = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
        try:
            while chunk := await file.read(_UPLOAD_CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise UploadTooLargeError(max_bytes)
                tmp.write(chunk)
        except Exception:
            _cleanup_temp_path(tmp_path)
            raise
    return tmp_path, total_bytes


class SynthesizeBody(BaseModel):
    text: str
    speaker_id: str = ""
    locale: str = "zh-TW"
    sample_rate: int = 24000
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)


# ---------------------------------------------------------------------------
# Health & metrics
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "service": "tts-router"}


@app.get("/metrics")
async def metrics() -> dict:
    return get_metrics_snapshot()


# ---------------------------------------------------------------------------
# TTS synthesis
# ---------------------------------------------------------------------------


@app.post("/v1/synthesize")
async def synthesize(body: SynthesizeBody) -> Response:
    svc = _get_service()
    request = SynthesizeRequest(
        text=body.text,
        locale=body.locale,
        sample_rate=body.sample_rate,
        voice_hint=body.speaker_id,
    )

    try:
        result = svc.synthesize(request)
    except RuntimeError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})

    return Response(
        content=result.audio_bytes,
        media_type=result.content_type,
        headers={
            "X-Request-Id": body.request_id,
            "X-TTS-Latency-Ms": str(round(result.latency_ms, 2)),
            "X-TTS-Provider": result.provider,
            "X-TTS-Route-Target": result.route_target,
            "X-Sample-Rate": str(result.sample_rate),
        },
    )


# ---------------------------------------------------------------------------
# MarkItDown — document-to-markdown conversion
# ---------------------------------------------------------------------------


@app.post("/convert")
async def convert(file: UploadFile = File(...)) -> JSONResponse:
    suffix = os.path.splitext(file.filename or "")[1]
    tmp_path: str | None = None
    cfg = get_tts_config()
    try:
        tmp_path, total_bytes = await _persist_upload_to_tempfile(
            file,
            suffix=suffix,
            max_bytes=cfg.markitdown_max_upload_bytes,
        )
        logger.info("Converting file: %s (%d bytes)", file.filename, total_bytes)
        result = _get_md_converter().convert(tmp_path)

        return JSONResponse(
            content={
                "markdown": result.text_content,
                "page_count": None,
            }
        )
    except UploadTooLargeError:
        return JSONResponse(
            status_code=413,
            content={"error": "uploaded file too large"},
        )
    except Exception as exc:
        logger.error("Conversion failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)},
        )
    finally:
        await file.close()
        _cleanup_temp_path(tmp_path)

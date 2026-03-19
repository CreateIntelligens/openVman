"""MediaDispatcher — MIME-based routing with timeout."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import get_tts_config
from app.gateway.ingestion import IngestionResult, ingest_document, is_document_type

logger = logging.getLogger("gateway.dispatcher")


def _route_mime(mime_type: str) -> str:
    """Map MIME type to handler category."""
    if is_document_type(mime_type):
        return "document"
    prefix = mime_type.split("/")[0]
    if prefix in ("image", "video", "audio"):
        return prefix
    return "unknown"


async def _process(category: str, file_path: str, trace_id: str) -> IngestionResult:
    """Call the appropriate ingestion function.

    Imports are kept at call-time so that handlers can be patched in tests.
    """
    if category == "document":
        return ingest_document(file_path, trace_id)

    if category == "image":
        from app.gateway.ingestion_image import describe as describe_image
        return await describe_image(file_path, trace_id)

    if category == "audio":
        from app.gateway.ingestion_audio import transcribe as transcribe_audio
        return await transcribe_audio(file_path, trace_id)

    if category == "video":
        from app.gateway.ingestion_video import describe as describe_video
        return await describe_video(file_path, trace_id)

    return IngestionResult(
        content_type="unsupported",
        content=f"no handler for category: {category}",
    )


def _build_result(result: IngestionResult, mime_type: str) -> dict[str, Any]:
    """Build a standard response dict from an IngestionResult."""
    return {
        "type": result.content_type,
        "content": result.content,
        "page_count": result.page_count,
        "mime_type": mime_type,
    }


async def dispatch(file_path: str, mime_type: str, trace_id: str) -> dict[str, Any]:
    """Route media to the appropriate ingestion handler.

    Applies a timeout from config.media_processing_timeout_ms.
    Returns a dict with at least {"type": ..., "content": ...}.
    """
    cfg = get_tts_config()
    category = _route_mime(mime_type)
    logger.info("dispatch trace_id=%s mime=%s category=%s", trace_id, mime_type, category)

    if category == "unknown":
        return {
            "type": "unsupported",
            "reason": f"unsupported MIME type: {mime_type}",
            "mime_type": mime_type,
        }

    timeout_sec = cfg.media_processing_timeout_ms / 1000.0

    try:
        result = await asyncio.wait_for(
            _process(category, file_path, trace_id),
            timeout=timeout_sec,
        )
        return _build_result(result, mime_type)
    except asyncio.TimeoutError:
        logger.error("dispatch_timeout trace_id=%s category=%s", trace_id, category)
        return {
            "type": "processing_error",
            "reason": f"processing timeout ({cfg.media_processing_timeout_ms}ms)",
            "mime_type": mime_type,
        }
    except Exception as exc:
        logger.error("dispatch_error trace_id=%s err=%s", trace_id, exc)
        return {
            "type": "processing_error",
            "reason": str(exc),
            "mime_type": mime_type,
        }

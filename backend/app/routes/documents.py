"""Convert uploaded files without storing or indexing their originals."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import anydoc
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from app.config import get_tts_config
from app.error_payloads import upload_failed_response
from app.utils.upload import (
    UploadTooLargeError,
    cleanup_temp_path,
    persist_upload_to_tempfile,
)

logger = logging.getLogger("backend")
router = APIRouter()
_PLAINTEXT_DOCUMENT_SUFFIXES = frozenset({".md", ".markdown", ".txt"})


def _convert_document_to_markdown(file_path: str) -> str:
    if Path(file_path).suffix.lower() in _PLAINTEXT_DOCUMENT_SUFFIXES:
        return Path(file_path).read_text(encoding="utf-8")
    return anydoc.to_markdown(file_path)


@router.post(
    "/api/v1/documents/convert",
    tags=["Documents"],
    summary="文件轉 Markdown",
    description="`.md`、`.markdown`、`.txt` 以 UTF-8 直接讀取；其餘格式使用 Firecrawl AnyDoc 轉換。本端點不保存原始檔，也不觸發知識庫索引。",
)
async def convert(file: UploadFile = File(...)) -> JSONResponse:
    suffix = os.path.splitext(file.filename or "")[1]
    tmp_path: str | None = None
    cfg = get_tts_config()
    try:
        tmp_path, total_bytes = await persist_upload_to_tempfile(
            file,
            suffix=suffix,
            max_bytes=cfg.document_max_upload_bytes,
        )
        logger.info("Converting file: %s (%d bytes)", file.filename, total_bytes)
        markdown = _convert_document_to_markdown(tmp_path)
        from app.utils.chinese import convert_to_traditional
        markdown = convert_to_traditional(markdown or "")
        return JSONResponse(content={"markdown": markdown, "page_count": None})
    except UploadTooLargeError as exc:
        limit_mb = exc.limit_bytes / (1024 * 1024)
        return upload_failed_response(
            status_code=413,
            error=f"檔案超過大小限制（上限 {limit_mb:.0f} MB）",
        )
    except Exception as exc:
        logger.error("Conversion failed: %s", exc)
        return upload_failed_response(
            status_code=500,
            error=str(exc),
        )
    finally:
        await file.close()
        cleanup_temp_path(tmp_path)

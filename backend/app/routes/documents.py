"""Convert uploaded files without storing or indexing their originals."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import anydoc
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from app.config import get_tts_config
from app.error_payloads import upload_failed_response, upload_rejected_response
from app.utils.document_checks import (
    DOCUMENT_SUFFIXES,
    check_document_upload,
    require_document_suffix,
)
from app.utils.upload import (
    UploadLimitError,
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
    description=(
        "`.md`、`.markdown`、`.txt` 以 UTF-8 直接讀取；其餘格式使用 Firecrawl AnyDoc 轉換。"
        "本端點不保存原始檔，也不觸發知識庫索引。\n\n"
        f"只接受 {'、'.join(sorted(DOCUMENT_SUFFIXES))}；超過 `DOCUMENT_MAX_UPLOAD_BYTES`"
        "（預設 100 MB）或 Office 檔解壓後總量、內含檔案數超過設定上限回 413，"
        "格式不符回 415。"
    ),
)
async def convert(file: UploadFile = File(...)) -> JSONResponse:
    tmp_path: str | None = None
    cfg = get_tts_config()
    try:
        suffix = require_document_suffix(file.filename or "")
        tmp_path, total_bytes = await persist_upload_to_tempfile(
            file,
            suffix=suffix,
            max_bytes=cfg.document_max_upload_bytes,
        )
        await asyncio.to_thread(check_document_upload, tmp_path, suffix, cfg=cfg)
        logger.info("Converting file: %s (%d bytes)", file.filename, total_bytes)
        markdown = _convert_document_to_markdown(tmp_path)
        from app.utils.chinese import convert_to_traditional
        markdown = convert_to_traditional(markdown or "")
        return JSONResponse(content={"markdown": markdown, "page_count": None})
    except UploadLimitError as exc:
        return upload_rejected_response(exc)
    except Exception as exc:
        logger.error("Conversion failed: %s", exc)
        return upload_failed_response(
            status_code=500,
            error=str(exc),
        )
    finally:
        await file.close()
        cleanup_temp_path(tmp_path)

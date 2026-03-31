"""Document ingestion via Docling with MarkItDown fallback."""

from __future__ import annotations

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import TTSRouterConfig, get_tts_config

logger = logging.getLogger("gateway.ingestion")
logging.getLogger("pdfminer").setLevel(logging.ERROR)

_md_converter: Any = None
_DOCLING_SUPPORTED_SUFFIXES = frozenset({".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"})


class DocumentIngestionError(RuntimeError):
    """Raised when document conversion fails."""


class DoclingServiceError(DocumentIngestionError):
    """Raised when docling-serve cannot provide usable markdown."""


def _get_md_converter() -> Any:
    global _md_converter
    if _md_converter is None:
        from markitdown import MarkItDown
        _md_converter = MarkItDown()
    return _md_converter


def _docling_headers(cfg: TTSRouterConfig) -> dict[str, str]:
    headers: dict[str, str] = {}
    if cfg.docling_api_key.strip():
        headers["X-Api-Key"] = cfg.docling_api_key.strip()
    return headers


def _extract_docling_markdown(payload: dict[str, Any]) -> str:
    document = payload.get("document")
    if isinstance(document, dict):
        markdown = document.get("md_content")
        if isinstance(markdown, str):
            return markdown
    markdown = payload.get("md_content")
    if isinstance(markdown, str):
        return markdown
    raise DoclingServiceError("docling response missing markdown content")


def _convert_with_docling(file_path: str, trace_id: str, cfg: TTSRouterConfig) -> str:
    path = Path(file_path)
    files = {
        "files": (path.name, path.read_bytes(), "application/octet-stream"),
    }
    data = {
        "target_type": "INBODY",
        "to_formats": "md",
    }
    logger.info("docling_ingest_start trace_id=%s path=%s", trace_id, file_path)
    try:
        response = httpx.post(
            f"{cfg.docling_serve_url.rstrip('/')}/v1/convert/file",
            files=files,
            data=data,
            headers=_docling_headers(cfg),
            timeout=cfg.docling_timeout_ms / 1000.0,
        )
        response.raise_for_status()
        markdown = _extract_docling_markdown(response.json())
    except httpx.TimeoutException as exc:
        raise DoclingServiceError("docling request timed out") from exc
    except httpx.HTTPStatusError as exc:
        raise DoclingServiceError(f"docling returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise DoclingServiceError("docling request failed") from exc
    except ValueError as exc:
        raise DoclingServiceError("docling returned invalid JSON") from exc

    logger.info("docling_ingest_complete trace_id=%s chars=%d", trace_id, len(markdown))
    return markdown


def _convert_with_markitdown(file_path: str, trace_id: str) -> str:
    logger.info("markitdown_ingest_start trace_id=%s path=%s", trace_id, file_path)
    converter = _get_md_converter()
    result = converter.convert(file_path)
    markdown = result.text_content or ""
    logger.info("markitdown_ingest_complete trace_id=%s chars=%d", trace_id, len(markdown))
    return markdown


@dataclass(frozen=True)
class IngestionResult:
    content_type: str  # "document_content"
    content: str
    page_count: int | None = None


_DOCUMENT_MIME_TYPES = frozenset({
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
})


def is_document_type(mime_type: str) -> bool:
    return mime_type in _DOCUMENT_MIME_TYPES


def ingest_document(file_path: str, trace_id: str, cfg: TTSRouterConfig | None = None) -> IngestionResult:
    cfg = cfg or get_tts_config()
    suffix = Path(file_path).suffix.lower()
    use_docling = suffix in _DOCLING_SUPPORTED_SUFFIXES

    try:
        markdown = _convert_with_docling(file_path, trace_id, cfg) if use_docling else _convert_with_markitdown(file_path, trace_id)
    except DoclingServiceError as exc:
        if use_docling and cfg.docling_fallback_to_markitdown:
            logger.warning("docling_ingest_failed trace_id=%s err=%s fallback=markitdown", trace_id, exc)
            markdown = _convert_with_markitdown(file_path, trace_id)
        else:
            logger.error("document_ingest_failed trace_id=%s err=%s", trace_id, exc)
            raise

    return IngestionResult(
        content_type="document_content",
        content=markdown,
        page_count=None,
    )

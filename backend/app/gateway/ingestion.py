"""Document ingestion via Docling with MarkItDown fallback."""

from __future__ import annotations

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from app.config import TTSRouterConfig, get_tts_config

logger = logging.getLogger("gateway.ingestion")
logging.getLogger("pdfminer").setLevel(logging.ERROR)

_md_converter: Any = None
_DOCLING_SUPPORTED_SUFFIXES = frozenset({".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"})


class DocumentIngestionError(RuntimeError):
    """Raised when document conversion fails."""


class DoclingServiceError(DocumentIngestionError):
    """Raised when docling-serve cannot provide usable markdown."""


def _get_converter(name: str) -> Any:
    """Lazy-load and return a converter by name."""
    global _md_converter, _docling_converter
    if name == "markitdown":
        if _md_converter is None:
            from markitdown import MarkItDown
            _md_converter = MarkItDown()
        return _md_converter
    elif name == "docling":
        if _docling_converter is None:
            from docling.document_converter import DocumentConverter
            _docling_converter = DocumentConverter()
        return _docling_converter
    return None


def _convert(file_path: str, trace_id: str, provider: str) -> str:
    logger.info("%s_ingest_start trace_id=%s path=%s", provider, trace_id, file_path)
    converter = _get_converter(provider)
    try:
        result = converter.convert(file_path)
        if provider == "docling":
            markdown = result.document.export_to_markdown()
        else:
            markdown = result.text_content or ""
    except Exception as exc:
        if provider == "docling":
            raise DoclingServiceError(f"docling conversion failed: {exc}") from exc
        raise DocumentIngestionError(f"markitdown conversion failed: {exc}") from exc

    logger.info("%s_ingest_complete trace_id=%s chars=%d", provider, trace_id, len(markdown))
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
        markdown = _convert(file_path, trace_id, "docling" if use_docling else "markitdown")
    except DoclingServiceError as exc:
        if cfg.docling_fallback_to_markitdown:
            logger.warning("docling_ingest_failed trace_id=%s err=%s fallback=markitdown", trace_id, exc)
            markdown = _convert(file_path, trace_id, "markitdown")
        else:
            logger.error("document_ingest_failed trace_id=%s err=%s", trace_id, exc)
            raise

    return IngestionResult(
        content_type="document_content",
        content=markdown,
        page_count=None,
    )

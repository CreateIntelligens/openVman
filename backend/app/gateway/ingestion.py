"""Document ingestion via MarkItDown (in-process)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("gateway.ingestion")
logging.getLogger("pdfminer").setLevel(logging.ERROR)

_md_converter: Any = None


def _get_md_converter() -> Any:
    global _md_converter
    if _md_converter is None:
        from markitdown import MarkItDown
        _md_converter = MarkItDown()
    return _md_converter


@dataclass(frozen=True)
class IngestionResult:
    content_type: str  # "document_content"
    content: str
    page_count: int | None = None


_DOCUMENT_MIME_TYPES = frozenset({
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
})


def is_document_type(mime_type: str) -> bool:
    return mime_type in _DOCUMENT_MIME_TYPES


def ingest_document(file_path: str, trace_id: str) -> IngestionResult:
    logger.info("ingesting document path=%s trace_id=%s", file_path, trace_id)
    converter = _get_md_converter()
    result = converter.convert(file_path)
    markdown = result.text_content or ""
    logger.info("ingestion complete trace_id=%s chars=%d", trace_id, len(markdown))
    return IngestionResult(
        content_type="document_content",
        content=markdown,
        page_count=None,
    )

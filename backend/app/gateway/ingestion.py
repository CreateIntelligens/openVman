"""Document ingestion via pdf-inspector, Docling, and MarkItDown fallback."""

from __future__ import annotations

import importlib
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import TTSRouterConfig, get_tts_config

logger = logging.getLogger("gateway.ingestion")
logging.getLogger("pdfminer").setLevel(logging.ERROR)

_md_converter: Any = None
_docling_converter: Any = None
_DOCLING_SUPPORTED_SUFFIXES = frozenset({
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
})
_PDF_STRUCTURE_ERROR_KEYWORDS = frozenset({
    "pdfium",
    "pdfminer",
    "invalid pdf",
    "format error",
    "corrupt",
    "xref",
    "eof",
    "syntax error",
    "not valid pdf",
    "structure",
    "parser error",
    "docling not valid",
})
_PDF_REPAIR_BACKENDS = (
    ("qpdf", ("qpdf", "{input_path}", "{output_path}")),
    ("mutool", ("mutool", "clean", "{input_path}", "{output_path}")),
    (
        "ghostscript",
        ("gs", "-o", "{output_path}", "-sDEVICE=pdfwrite", "{input_path}"),
    ),
)
_PDF_INSPECTOR_MIN_CONFIDENCE_DEFAULT = 0.85
_PDF_INSPECTOR_MIN_MARKDOWN_CHARS_DEFAULT = 10
_PDF_REPAIR_TIMEOUT_MS_DEFAULT = 120000


class DocumentIngestionError(RuntimeError):
    """Raised when document conversion fails."""


class DoclingServiceError(DocumentIngestionError):
    """Raised when Docling cannot provide usable markdown."""


class PDFRepairError(DocumentIngestionError):
    """Raised when PDF repair fails after trying all backends."""


def _get_pdf_page_count(file_path: str) -> int | None:
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(file_path)
        return len(doc)
    except Exception:
        return None


def _is_pdf_structure_failure(file_path: str, exception: Exception) -> bool:
    if _get_pdf_page_count(file_path) is None:
        return True

    msg = str(exception).lower()
    return any(keyword in msg for keyword in _PDF_STRUCTURE_ERROR_KEYWORDS)


def _lightweight_pdf_sanity_check(file_path: str) -> bool:
    path = Path(file_path)
    if not path.is_file():
        return False
    if path.stat().st_size < 100:
        return False

    pages = _get_pdf_page_count(file_path)
    return pages is not None and pages > 0


def _run_cmd(cmd: list[str], timeout_sec: float) -> bool:
    executable = cmd[0]
    try:
        if not shutil.which(executable):
            logger.warning("pdf_repair_executable_missing cmd=%s", executable)
            return False

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        allowed_codes = {0, 3} if executable == "qpdf" else {0}
        if result.returncode in allowed_codes:
            return True
        logger.warning(
            "pdf_repair_command_failed cmd=%s code=%d stdout=%s stderr=%s",
            executable,
            result.returncode,
            result.stdout,
            result.stderr,
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("pdf_repair_command_timeout cmd=%s", executable)
        return False
    except Exception as exc:
        logger.warning("pdf_repair_command_exception cmd=%s err=%s", executable, exc)
        return False


def _get_converter(name: str) -> Any:
    """Lazy-load and return a converter by name."""
    global _md_converter, _docling_converter
    if name == "markitdown":
        if _md_converter is None:
            from markitdown import MarkItDown

            _md_converter = MarkItDown()
        return _md_converter

    if name == "docling":
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


def _normalize_pdf_type(value: Any) -> str:
    normalized = str(value or "").strip().replace("-", "_").replace(" ", "_").lower()
    if normalized == "textbased":
        return "text_based"
    if normalized == "imagebased":
        return "image_based"
    return normalized


def _can_use_pdf_inspector_markdown(
    *,
    pdf_type: str,
    confidence: float,
    markdown_chars: int,
    min_confidence: float,
    min_markdown_chars: int,
    pages_needing_ocr: Any,
    has_encoding_issues: bool,
) -> bool:
    return (
        pdf_type == "text_based"
        and confidence >= min_confidence
        and markdown_chars >= min_markdown_chars
        and not pages_needing_ocr
        and not has_encoding_issues
    )


def _try_pdf_inspector(file_path: str, trace_id: str, cfg: TTSRouterConfig) -> str | None:
    if not getattr(cfg, "pdf_inspector_enabled", True):
        return None
    if Path(file_path).suffix.lower() != ".pdf":
        return None

    try:
        pdf_inspector = importlib.import_module("pdf_inspector")
    except Exception as exc:
        logger.debug("pdf_inspector_unavailable trace_id=%s err=%s", trace_id, exc)
        return None

    try:
        result = pdf_inspector.process_pdf(file_path)
    except Exception as exc:
        logger.warning(
            "pdf_inspector_failed trace_id=%s err=%s fallback=docling",
            trace_id,
            exc,
        )
        return None

    markdown = getattr(result, "markdown", None) or ""
    markdown_chars = len(markdown.strip())
    pdf_type = _normalize_pdf_type(getattr(result, "pdf_type", ""))
    confidence = float(getattr(result, "confidence", 0.0) or 0.0)
    pages_needing_ocr = getattr(result, "pages_needing_ocr", None) or []
    has_encoding_issues = bool(getattr(result, "has_encoding_issues", False))
    min_confidence = float(
        getattr(
            cfg,
            "pdf_inspector_min_confidence",
            _PDF_INSPECTOR_MIN_CONFIDENCE_DEFAULT,
        )
    )
    min_markdown_chars = int(
        getattr(
            cfg,
            "pdf_inspector_min_markdown_chars",
            _PDF_INSPECTOR_MIN_MARKDOWN_CHARS_DEFAULT,
        )
    )

    if _can_use_pdf_inspector_markdown(
        pdf_type=pdf_type,
        confidence=confidence,
        markdown_chars=markdown_chars,
        min_confidence=min_confidence,
        min_markdown_chars=min_markdown_chars,
        pages_needing_ocr=pages_needing_ocr,
        has_encoding_issues=has_encoding_issues,
    ):
        logger.info(
            "pdf_inspector_ok trace_id=%s chars=%d confidence=%.3f",
            trace_id,
            markdown_chars,
            confidence,
        )
        return markdown

    logger.info(
        "pdf_inspector_fallback trace_id=%s pdf_type=%s confidence=%.3f "
        "pages_needing_ocr=%d encoding_issues=%s markdown_chars=%d",
        trace_id,
        pdf_type,
        confidence,
        len(pages_needing_ocr),
        has_encoding_issues,
        markdown_chars,
    )
    return None


@dataclass(frozen=True)
class IngestionResult:
    content_type: str  # "document_content"
    content: str
    page_count: int | None = None


def _to_ingestion_result(content: str, *, page_count: int | None = None) -> IngestionResult:
    from app.utils.chinese import convert_to_traditional
    content = convert_to_traditional(content)
    return IngestionResult(
        content_type="document_content",
        content=content,
        page_count=page_count,
    )


def _convert_with_docling_fallback(
    file_path: str,
    trace_id: str,
    cfg: TTSRouterConfig,
    provider: str,
) -> str:
    try:
        return _convert(file_path, trace_id, provider)
    except DoclingServiceError as exc:
        if provider != "docling" or not cfg.docling_fallback_to_markitdown:
            raise

        logger.warning(
            "docling_ingest_failed trace_id=%s err=%s fallback=markitdown",
            trace_id,
            exc,
        )
        return _convert(file_path, trace_id, "markitdown")


def _ingest_without_repair(
    file_path: str,
    trace_id: str,
    cfg: TTSRouterConfig,
    provider: str,
) -> str:
    pdf_inspector_markdown = _try_pdf_inspector(file_path, trace_id, cfg)
    if pdf_inspector_markdown is not None:
        return pdf_inspector_markdown

    return _convert_with_docling_fallback(file_path, trace_id, cfg, provider)


def _remove_temp_file(path: Path, trace_id: str) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(
            "pdf_repair_temp_cleanup_failed trace_id=%s path=%s err=%s",
            trace_id,
            path,
            exc,
        )


def _build_repair_command(
    template: tuple[str, ...],
    input_path: str,
    output_path: str,
) -> list[str]:
    return [
        arg.format(input_path=input_path, output_path=output_path)
        for arg in template
    ]


def _convert_repaired_pdf(file_path: str, trace_id: str, cfg: TTSRouterConfig) -> str:
    pdf_inspector_markdown = _try_pdf_inspector(file_path, trace_id, cfg)
    if pdf_inspector_markdown is not None:
        return pdf_inspector_markdown

    return _convert_with_docling_fallback(file_path, trace_id, cfg, "docling")


def _attempt_pdf_repair_backend(
    *,
    backend: str,
    command_template: tuple[str, ...],
    file_path: str,
    trace_id: str,
    cfg: TTSRouterConfig,
    timeout_sec: float,
    size_before: int,
    pages_before: int | None,
) -> IngestionResult | None:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        repaired_path = Path(tmp.name)

    try:
        repaired_file_path = str(repaired_path)
        command = _build_repair_command(command_template, file_path, repaired_file_path)
        if not _run_cmd(command, timeout_sec):
            return None

        if not _lightweight_pdf_sanity_check(repaired_file_path):
            return None

        try:
            repaired_markdown = _convert_repaired_pdf(repaired_file_path, trace_id, cfg)
        except Exception as exc:
            logger.warning(
                "pdf_repair_rerun_failed trace_id=%s backend=%s err=%s",
                trace_id,
                backend,
                exc,
            )
            return None

        if not repaired_markdown.strip():
            logger.warning(
                "pdf_repair_empty_markdown trace_id=%s backend=%s",
                trace_id,
                backend,
            )
            return None

        size_after = repaired_path.stat().st_size
        pages_after = _get_pdf_page_count(repaired_file_path)

        if backend == "ghostscript":
            logger.warning(
                "pdf_repair_rebuilt_caveat trace_id=%s "
                "message=This is a rebuilt PDF, not a lossless repair",
                trace_id,
            )

        logger.info(
            "pdf_repair_success trace_id=%s backend=%s size_before=%d "
            "size_after=%d pages_before=%s pages_after=%s",
            trace_id,
            backend,
            size_before,
            size_after,
            pages_before,
            pages_after,
        )
        return _to_ingestion_result(repaired_markdown, page_count=pages_after)
    except Exception as exc:
        logger.warning(
            "pdf_repair_backend_exception trace_id=%s backend=%s err=%s",
            trace_id,
            backend,
            exc,
        )
        return None
    finally:
        _remove_temp_file(repaired_path, trace_id)


def _repair_pdf(
    file_path: str,
    trace_id: str,
    cfg: TTSRouterConfig,
    initial_exc: Exception,
) -> IngestionResult:
    logger.info(
        "pdf_ingestion_failed_trigger_repair trace_id=%s err=%s",
        trace_id,
        initial_exc,
    )

    source_path = Path(file_path)
    size_before = source_path.stat().st_size
    pages_before = _get_pdf_page_count(file_path)
    timeout_sec = (
        float(getattr(cfg, "pdf_repair_timeout_ms", _PDF_REPAIR_TIMEOUT_MS_DEFAULT))
        / 1000.0
    )

    for backend, command_template in _PDF_REPAIR_BACKENDS:
        logger.info("pdf_repair_attempt trace_id=%s backend=%s", trace_id, backend)
        result = _attempt_pdf_repair_backend(
            backend=backend,
            command_template=command_template,
            file_path=file_path,
            trace_id=trace_id,
            cfg=cfg,
            timeout_sec=timeout_sec,
            size_before=size_before,
            pages_before=pages_before,
        )
        if result is not None:
            return result

    logger.error("pdf_repair_failed_all_backends trace_id=%s", trace_id)
    raise PDFRepairError(
        "PDF structure is corrupt and repair failed. Tried qpdf, mutool, and "
        f"ghostscript. Original error: {initial_exc}"
    ) from initial_exc

_DOCUMENT_MIME_TYPES = frozenset({
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
})


def is_document_type(mime_type: str) -> bool:
    return mime_type in _DOCUMENT_MIME_TYPES


def ingest_document(
    file_path: str,
    trace_id: str,
    cfg: TTSRouterConfig | None = None,
) -> IngestionResult:
    cfg = cfg or get_tts_config()
    suffix = Path(file_path).suffix.lower()
    provider = "docling" if suffix in _DOCLING_SUPPORTED_SUFFIXES else "markitdown"

    try:
        markdown = _ingest_without_repair(file_path, trace_id, cfg, provider)
        return _to_ingestion_result(markdown)
    except Exception as exc:
        initial_exc = exc

    if suffix != ".pdf" or not getattr(cfg, "pdf_repair_enabled", True):
        logger.error("document_ingest_failed trace_id=%s err=%s", trace_id, initial_exc)
        raise initial_exc

    if not _is_pdf_structure_failure(file_path, initial_exc):
        logger.error(
            "document_ingest_failed_non_structural trace_id=%s err=%s",
            trace_id,
            initial_exc,
        )
        raise initial_exc

    return _repair_pdf(file_path, trace_id, cfg, initial_exc)

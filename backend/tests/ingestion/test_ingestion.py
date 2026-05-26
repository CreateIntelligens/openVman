"""Tests for document ingestion."""

from __future__ import annotations

import logging
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.gateway.ingestion import (
    DoclingServiceError,
    PDFRepairError,
    ingest_document,
    is_document_type,
)

_INGESTION_MODULE = "app.gateway.ingestion"
_CONVERT = f"{_INGESTION_MODULE}._convert"
_GET_PDF_PAGE_COUNT = f"{_INGESTION_MODULE}._get_pdf_page_count"
_IS_PDF_STRUCTURE_FAILURE = f"{_INGESTION_MODULE}._is_pdf_structure_failure"
_LIGHTWEIGHT_PDF_SANITY_CHECK = f"{_INGESTION_MODULE}._lightweight_pdf_sanity_check"
_RUN_CMD = f"{_INGESTION_MODULE}._run_cmd"
_TRY_PDF_INSPECTOR = f"{_INGESTION_MODULE}._try_pdf_inspector"


def _cfg(*, fallback: bool = True):
    return SimpleNamespace(
        docling_serve_url="http://docling-serve:5001",
        docling_timeout_ms=5000,
        docling_api_key="",
        docling_fallback_to_markitdown=fallback,
        pdf_inspector_enabled=True,
        pdf_inspector_min_confidence=0.85,
        pdf_inspector_min_markdown_chars=10,
        pdf_repair_enabled=True,
        pdf_repair_timeout_ms=120000,
    )


def _install_pdf_inspector(monkeypatch: pytest.MonkeyPatch, result: SimpleNamespace):
    fake_pdf_inspector = SimpleNamespace(
        process_pdf=MagicMock(return_value=result),
    )
    monkeypatch.setitem(sys.modules, "pdf_inspector", fake_pdf_inspector)
    return fake_pdf_inspector


def _pdf_inspector_result(**overrides):
    values = {
        "pdf_type": "text_based",
        "confidence": 0.96,
        "markdown": "# Fast PDF\n\ncontent",
        "pages_needing_ocr": [],
        "has_encoding_issues": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _broken_pdf(tmp_path, name: str = "broken.pdf"):
    test_file = tmp_path / name
    test_file.write_bytes(b"broken")
    return test_file


def _record_commands(cmds_run: list[list[str]], *, success_for: str | None = None):
    def fake_run_cmd(cmd, timeout):
        cmds_run.append(cmd)
        return success_for is None or cmd[0] == success_for

    return fake_run_cmd


class TestIngestDocument:
    def test_pdf_inspector_text_based_pdf_returns_markdown_without_docling(
        self,
        tmp_path,
        monkeypatch,
    ):
        test_file = tmp_path / "fast.pdf"
        test_file.write_bytes(b"%PDF-1.4 fake")

        fake_pdf_inspector = _install_pdf_inspector(
            monkeypatch,
            _pdf_inspector_result(),
        )

        with patch(_CONVERT) as mock_convert:
            result = ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

        assert result.content == "# Fast PDF\n\ncontent"
        fake_pdf_inspector.process_pdf.assert_called_once_with(str(test_file))
        mock_convert.assert_not_called()

    def test_pdf_inspector_scanned_pdf_falls_back_to_docling(
        self,
        tmp_path,
        monkeypatch,
    ):
        test_file = tmp_path / "scan.pdf"
        test_file.write_bytes(b"%PDF-1.4 fake")

        fake_pdf_inspector = _install_pdf_inspector(
            monkeypatch,
            _pdf_inspector_result(
                pdf_type="scanned",
                confidence=0.99,
                markdown=None,
                pages_needing_ocr=[0],
            ),
        )

        with patch(
            _CONVERT,
            return_value="# Docling fallback\n",
        ) as mock_convert:
            result = ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

        assert result.content == "# Docling fallback\n"
        fake_pdf_inspector.process_pdf.assert_called_once_with(str(test_file))
        mock_convert.assert_called_once_with(str(test_file), "test-trace", "docling")

    def test_pdf_inspector_low_confidence_pdf_falls_back_to_docling(
        self,
        tmp_path,
        monkeypatch,
    ):
        test_file = tmp_path / "uncertain.pdf"
        test_file.write_bytes(b"%PDF-1.4 fake")

        _install_pdf_inspector(
            monkeypatch,
            _pdf_inspector_result(
                confidence=0.42,
                markdown="# Uncertain\n\ncontent",
            ),
        )

        with patch(
            _CONVERT,
            return_value="# Docling fallback\n",
        ) as mock_convert:
            result = ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

        assert result.content == "# Docling fallback\n"
        mock_convert.assert_called_once_with(str(test_file), "test-trace", "docling")

    def test_docling_document_returns_markdown(self, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"fake pdf content")

        with patch(
            _CONVERT,
            return_value="# Hello World\n\nThis is a test.",
        ) as mock_convert:
            result = ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

        assert result.content_type == "document_content"
        assert result.content == "# Hello World\n\nThis is a test."
        assert result.page_count is None
        mock_convert.assert_called_once_with(str(test_file), "test-trace", "docling")

    def test_markitdown_non_docling_suffix_returns_markdown(self, tmp_path):
        test_file = tmp_path / "page.txt"
        test_file.write_bytes(b"hello")

        with patch(
            _CONVERT,
            return_value="# Converted\n",
        ) as mock_convert:
            result = ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

        assert result.content == "# Converted\n"
        mock_convert.assert_called_once_with(str(test_file), "test-trace", "markitdown")

    def test_empty_content_returns_empty_string(self, tmp_path):
        test_file = tmp_path / "empty.pdf"
        test_file.write_bytes(b"")

        with patch(
            _CONVERT,
            return_value="",
        ):
            result = ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

        assert result.content == ""

    def test_docling_failure_falls_back_to_markitdown(self, tmp_path):
        test_file = tmp_path / "fallback.docx"
        test_file.write_bytes(b"docx")

        def side_effect(path, tid, provider):
            if provider == "docling":
                raise DoclingServiceError("boom")
            return "# Fallback\n"

        with patch(_CONVERT, side_effect=side_effect) as mock_convert:
            result = ingest_document(
                str(test_file),
                trace_id="test-trace",
                cfg=_cfg(fallback=True),
            )

        assert result.content == "# Fallback\n"
        assert mock_convert.call_count == 2

    def test_docling_failure_raises_without_fallback(self, tmp_path):
        test_file = tmp_path / "broken.pptx"
        test_file.write_bytes(b"pptx")

        with patch(
            _CONVERT,
            side_effect=DoclingServiceError("boom"),
        ):
            with pytest.raises(DoclingServiceError):
                ingest_document(
                    str(test_file),
                    trace_id="test-trace",
                    cfg=_cfg(fallback=False),
                )

    def test_pdf_repair_disabled_does_not_trigger_repair(self, tmp_path):
        test_file = _broken_pdf(tmp_path)
        cfg = _cfg()
        cfg.pdf_repair_enabled = False

        with (
            patch(_TRY_PDF_INSPECTOR, return_value=None),
            patch(_CONVERT, side_effect=DoclingServiceError("corrupt")),
            patch(_RUN_CMD) as mock_run_cmd,
        ):
            with pytest.raises(DoclingServiceError):
                ingest_document(str(test_file), trace_id="test-trace", cfg=cfg)

            mock_run_cmd.assert_not_called()

    def test_pdf_repair_skipped_on_non_structural_error(self, tmp_path):
        test_file = _broken_pdf(tmp_path)

        with (
            patch(_TRY_PDF_INSPECTOR, return_value=None),
            patch(_CONVERT, side_effect=DoclingServiceError("timeout")),
            patch(_IS_PDF_STRUCTURE_FAILURE, return_value=False),
            patch(_RUN_CMD) as mock_run_cmd,
        ):
            with pytest.raises(DoclingServiceError):
                ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

            mock_run_cmd.assert_not_called()

    def test_pdf_repair_qpdf_success(self, tmp_path):
        test_file = _broken_pdf(tmp_path)
        cmds_run: list[list[str]] = []

        with (
            patch(_TRY_PDF_INSPECTOR, side_effect=[None, "# Repaired Markdown\n"]),
            patch(_CONVERT, side_effect=DoclingServiceError("corrupt")),
            patch(_IS_PDF_STRUCTURE_FAILURE, return_value=True),
            patch(_GET_PDF_PAGE_COUNT, return_value=5),
            patch(_RUN_CMD, side_effect=_record_commands(cmds_run)),
            patch(_LIGHTWEIGHT_PDF_SANITY_CHECK, return_value=True),
        ):
            result = ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

        assert result.content == "# Repaired Markdown\n"
        assert result.page_count == 5
        assert len(cmds_run) == 1
        assert cmds_run[0][0] == "qpdf"

    def test_pdf_repair_mutool_success(self, tmp_path):
        test_file = _broken_pdf(tmp_path)
        cmds_run: list[list[str]] = []

        with (
            patch(_TRY_PDF_INSPECTOR, side_effect=[None, "# Repaired Mutool\n"]),
            patch(_CONVERT, side_effect=DoclingServiceError("corrupt")),
            patch(_IS_PDF_STRUCTURE_FAILURE, return_value=True),
            patch(_GET_PDF_PAGE_COUNT, return_value=3),
            patch(_RUN_CMD, side_effect=_record_commands(cmds_run, success_for="mutool")),
            patch(_LIGHTWEIGHT_PDF_SANITY_CHECK, return_value=True),
        ):
            result = ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

        assert result.content == "# Repaired Mutool\n"
        assert result.page_count == 3
        assert len(cmds_run) == 2
        assert cmds_run[0][0] == "qpdf"
        assert cmds_run[1][0] == "mutool"

    def test_pdf_repair_gs_success_with_caveat_logged(self, tmp_path, caplog):
        test_file = _broken_pdf(tmp_path)
        cmds_run: list[list[str]] = []

        with (
            caplog.at_level(logging.WARNING),
            patch(_TRY_PDF_INSPECTOR, side_effect=[None, "# Rebuilt gs\n"]),
            patch(_CONVERT, side_effect=DoclingServiceError("corrupt")),
            patch(_IS_PDF_STRUCTURE_FAILURE, return_value=True),
            patch(_GET_PDF_PAGE_COUNT, return_value=10),
            patch(_RUN_CMD, side_effect=_record_commands(cmds_run, success_for="gs")),
            patch(_LIGHTWEIGHT_PDF_SANITY_CHECK, return_value=True),
        ):
            result = ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

        assert result.content == "# Rebuilt gs\n"
        assert result.page_count == 10
        assert len(cmds_run) == 3
        assert cmds_run[2][0] == "gs"
        assert any(
            "This is a rebuilt PDF, not a lossless repair" in record.message
            for record in caplog.records
        )

    def test_pdf_repair_all_backends_fail(self, tmp_path):
        test_file = _broken_pdf(tmp_path)

        with (
            patch(_TRY_PDF_INSPECTOR, return_value=None),
            patch(_CONVERT, side_effect=DoclingServiceError("corrupt")),
            patch(_IS_PDF_STRUCTURE_FAILURE, return_value=True),
            patch(_RUN_CMD, return_value=False),
        ):
            with pytest.raises(PDFRepairError) as exc_info:
                ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

            assert "PDF structure is corrupt and repair failed" in str(exc_info.value)

    def test_pdf_repair_empty_markdown_falls_through_to_next_backend(self, tmp_path):
        """Repair sanity check passes but conversion returns empty markdown and must not
        be treated as success. Loop should continue to the next backend."""
        test_file = _broken_pdf(tmp_path)
        cmds_run: list[list[str]] = []

        # Initial pdf_inspector returns None; qpdf then yields empty content, so
        # mutool must be tried and can produce real markdown.
        inspector_side_effects = [None, "", "# Recovered\n"]

        with (
            patch(_TRY_PDF_INSPECTOR, side_effect=inspector_side_effects),
            patch(_CONVERT, side_effect=DoclingServiceError("corrupt")),
            patch(_IS_PDF_STRUCTURE_FAILURE, return_value=True),
            patch(_GET_PDF_PAGE_COUNT, return_value=2),
            patch(_RUN_CMD, side_effect=_record_commands(cmds_run)),
            patch(_LIGHTWEIGHT_PDF_SANITY_CHECK, return_value=True),
        ):
            result = ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

        assert result.content == "# Recovered\n"
        # qpdf attempt produced empty content, so mutool must also have been tried.
        assert [c[0] for c in cmds_run] == ["qpdf", "mutool"]

    def test_pdf_repair_all_backends_return_empty_markdown_raises(self, tmp_path):
        """If every repair backend yields empty markdown, PDFRepairError is raised."""
        test_file = _broken_pdf(tmp_path)

        # Initial inspector None, then qpdf/mutool/gs reruns all yield blank strings.
        inspector_side_effects = [None, "", "   \n", ""]

        with (
            patch(_TRY_PDF_INSPECTOR, side_effect=inspector_side_effects),
            patch(_CONVERT, side_effect=DoclingServiceError("corrupt")),
            patch(_IS_PDF_STRUCTURE_FAILURE, return_value=True),
            patch(_GET_PDF_PAGE_COUNT, return_value=1),
            patch(_RUN_CMD, return_value=True),
            patch(_LIGHTWEIGHT_PDF_SANITY_CHECK, return_value=True),
        ):
            with pytest.raises(PDFRepairError):
                ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())


class TestIsDocumentType:
    def test_pdf_is_document(self):
        assert is_document_type("application/pdf") is True

    def test_docx_is_document(self):
        assert is_document_type(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ) is True

    def test_pptx_is_document(self):
        assert is_document_type(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ) is True

    def test_xlsx_is_document(self):
        assert is_document_type(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ) is True

    def test_image_is_not_document(self):
        assert is_document_type("image/jpeg") is False

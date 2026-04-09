"""Tests for document ingestion."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.gateway.ingestion import DoclingServiceError, ingest_document, is_document_type


def _cfg(*, fallback: bool = True):
    return SimpleNamespace(
        docling_serve_url="http://docling-serve:5001",
        docling_timeout_ms=5000,
        docling_api_key="",
        docling_fallback_to_markitdown=fallback,
    )


class TestIngestDocument:
    def test_docling_document_returns_markdown(self, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"fake pdf content")

        with patch(
            "app.gateway.ingestion._convert_with_docling",
            return_value="# Hello World\n\nThis is a test.",
        ) as mock_docling:
            result = ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

        assert result.content_type == "document_content"
        assert result.content == "# Hello World\n\nThis is a test."
        assert result.page_count is None
        mock_docling.assert_called_once()

    def test_markitdown_non_docling_suffix_returns_markdown(self, tmp_path):
        test_file = tmp_path / "page.txt"
        test_file.write_bytes(b"hello")

        with patch(
            "app.gateway.ingestion._convert_with_markitdown",
            return_value="# Converted\n",
        ) as mock_markitdown:
            result = ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

        assert result.content == "# Converted\n"
        mock_markitdown.assert_called_once()

    def test_empty_content_returns_empty_string(self, tmp_path):
        test_file = tmp_path / "empty.pdf"
        test_file.write_bytes(b"")

        with patch(
            "app.gateway.ingestion._convert_with_docling",
            return_value="",
        ):
            result = ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg())

        assert result.content == ""

    def test_docling_failure_falls_back_to_markitdown(self, tmp_path):
        test_file = tmp_path / "fallback.docx"
        test_file.write_bytes(b"docx")

        with (
            patch(
                "app.gateway.ingestion._convert_with_docling",
                side_effect=DoclingServiceError("boom"),
            ),
            patch(
                "app.gateway.ingestion._convert_with_markitdown",
                return_value="# Fallback\n",
            ) as mock_markitdown,
        ):
            result = ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg(fallback=True))

        assert result.content == "# Fallback\n"
        mock_markitdown.assert_called_once()

    def test_docling_failure_raises_without_fallback(self, tmp_path):
        test_file = tmp_path / "broken.pptx"
        test_file.write_bytes(b"pptx")

        with patch(
            "app.gateway.ingestion._convert_with_docling",
            side_effect=DoclingServiceError("boom"),
        ):
            with pytest.raises(DoclingServiceError):
                ingest_document(str(test_file), trace_id="test-trace", cfg=_cfg(fallback=False))


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

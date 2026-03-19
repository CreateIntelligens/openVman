"""Tests for document ingestion."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.gateway.ingestion import ingest_document, is_document_type


class TestIngestDocument:
    def test_document_returns_markdown(self, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"fake pdf content")

        mock_result = MagicMock()
        mock_result.text_content = "# Hello World\n\nThis is a test."

        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_result

        with patch("app.gateway.ingestion._md_converter", mock_converter):
            result = ingest_document(str(test_file), trace_id="test-trace")

        assert result.content_type == "document_content"
        assert result.content == "# Hello World\n\nThis is a test."
        assert result.page_count is None
        mock_converter.convert.assert_called_once_with(str(test_file))

    def test_empty_content_returns_empty_string(self, tmp_path):
        test_file = tmp_path / "empty.pdf"
        test_file.write_bytes(b"")

        mock_result = MagicMock()
        mock_result.text_content = None

        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_result

        with patch("app.gateway.ingestion._md_converter", mock_converter):
            result = ingest_document(str(test_file), trace_id="test-trace")

        assert result.content == ""


class TestIsDocumentType:
    def test_pdf_is_document(self):
        assert is_document_type("application/pdf") is True

    def test_docx_is_document(self):
        assert is_document_type(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ) is True

    def test_image_is_not_document(self):
        assert is_document_type("image/jpeg") is False

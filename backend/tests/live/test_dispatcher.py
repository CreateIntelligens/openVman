"""Tests for MediaDispatcher."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gateway.dispatcher import _route_mime, dispatch
from app.gateway.ingestion import IngestionResult


class TestRouteMime:
    def test_pdf(self):
        assert _route_mime("application/pdf") == "document"

    def test_docx(self):
        assert _route_mime(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ) == "document"

    def test_pptx(self):
        assert _route_mime(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ) == "document"

    def test_xlsx(self):
        assert _route_mime(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ) == "document"

    def test_image(self):
        assert _route_mime("image/jpeg") == "image"
        assert _route_mime("image/png") == "image"
        assert _route_mime("image/webp") == "image"

    def test_video(self):
        assert _route_mime("video/mp4") == "video"
        assert _route_mime("video/quicktime") == "video"

    def test_audio(self):
        assert _route_mime("audio/mpeg") == "audio"
        assert _route_mime("audio/wav") == "audio"

    def test_unknown(self):
        assert _route_mime("application/octet-stream") == "unknown"


def _mock_cfg(timeout_ms: int = 5000) -> MagicMock:
    return MagicMock(media_processing_timeout_ms=timeout_ms)


class TestDispatch:
    @pytest.mark.asyncio
    async def test_image_dispatch(self):
        fake_result = IngestionResult(content_type="image_description", content="描述")

        with (
            patch("app.gateway.dispatcher.get_tts_config", return_value=_mock_cfg()),
            patch("app.gateway.ingestion_image.describe", new_callable=AsyncMock, return_value=fake_result),
        ):
            result = await dispatch("/tmp/test.jpg", "image/jpeg", "t1")

        assert result["type"] == "image_description"
        assert result["content"] == "描述"

    @pytest.mark.asyncio
    async def test_audio_dispatch(self):
        fake_result = IngestionResult(content_type="audio_transcription", content="轉錄")

        with (
            patch("app.gateway.dispatcher.get_tts_config", return_value=_mock_cfg()),
            patch("app.gateway.ingestion_audio.transcribe", new_callable=AsyncMock, return_value=fake_result),
        ):
            result = await dispatch("/tmp/test.mp3", "audio/mpeg", "t2")

        assert result["type"] == "audio_transcription"

    @pytest.mark.asyncio
    async def test_video_dispatch(self):
        fake_result = IngestionResult(content_type="video_description", content="影片")

        with (
            patch("app.gateway.dispatcher.get_tts_config", return_value=_mock_cfg()),
            patch("app.gateway.ingestion_video.describe", new_callable=AsyncMock, return_value=fake_result),
        ):
            result = await dispatch("/tmp/test.mp4", "video/mp4", "t3")

        assert result["type"] == "video_description"

    @pytest.mark.asyncio
    async def test_document_dispatch(self):
        fake_result = IngestionResult(content_type="document_content", content="文件")

        with (
            patch("app.gateway.dispatcher.get_tts_config", return_value=_mock_cfg()),
            patch("app.gateway.dispatcher.ingest_document", return_value=fake_result),
        ):
            result = await dispatch("/tmp/test.pdf", "application/pdf", "t4")

        assert result["type"] == "document_content"

    @pytest.mark.asyncio
    async def test_unknown_type(self):
        with patch("app.gateway.dispatcher.get_tts_config", return_value=_mock_cfg()):
            result = await dispatch("/tmp/test.bin", "application/octet-stream", "t5")

        assert result["type"] == "unsupported"

    @pytest.mark.asyncio
    async def test_timeout(self):
        async def slow_describe(path, tid):
            await asyncio.sleep(10)
            return IngestionResult(content_type="image_description", content="")

        with (
            patch("app.gateway.dispatcher.get_tts_config", return_value=_mock_cfg(timeout_ms=100)),
            patch("app.gateway.ingestion_image.describe", side_effect=slow_describe),
        ):
            result = await dispatch("/tmp/test.jpg", "image/jpeg", "t6")

        assert result["type"] == "processing_error"
        assert result["error_code"] == "GATEWAY_TIMEOUT"
        assert "timeout" in result["reason"]

    @pytest.mark.asyncio
    async def test_processing_error(self):
        with (
            patch("app.gateway.dispatcher.get_tts_config", return_value=_mock_cfg()),
            patch("app.gateway.ingestion_image.describe", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
        ):
            result = await dispatch("/tmp/test.jpg", "image/jpeg", "t7")

        assert result["type"] == "processing_error"
        assert "boom" in result["reason"]

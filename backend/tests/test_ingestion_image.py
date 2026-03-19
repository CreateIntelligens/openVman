"""Tests for image ingestion."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gateway.ingestion_image import describe


@pytest.fixture
def _fake_image(tmp_path):
    """Create a minimal valid PNG file."""
    import struct
    import zlib

    def _make_png() -> bytes:
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
        raw = b"\x00\xff\x00\x00"
        compressed = zlib.compress(raw)
        idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
        idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)
        iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
        return sig + ihdr + idat + iend

    path = tmp_path / "test.png"
    path.write_bytes(_make_png())
    return str(path)


def _make_mock_openai_client(content: str) -> MagicMock:
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    return mock_client


def _vision_cfg(*, api_key: str = "test-key", base_url: str = "") -> MagicMock:
    return MagicMock(
        vision_llm_api_key=api_key,
        vision_llm_model="gpt-4o",
        vision_llm_base_url=base_url,
    )


class TestDescribeWithVision:
    @pytest.mark.asyncio
    async def test_vision_llm_success(self, _fake_image):
        mock_client = _make_mock_openai_client("這是一張測試圖片")

        with (
            patch("app.gateway.ingestion_image.get_tts_config", return_value=_vision_cfg()),
            patch("app.gateway.ingestion_image.AsyncOpenAI", return_value=mock_client),
        ):
            result = await describe(_fake_image, "trace-1")

        assert result.content_type == "image_description"
        assert result.content == "這是一張測試圖片"

    @pytest.mark.asyncio
    async def test_vision_llm_with_base_url(self, _fake_image):
        mock_client = _make_mock_openai_client("描述結果")

        with (
            patch("app.gateway.ingestion_image.get_tts_config", return_value=_vision_cfg(base_url="https://custom.api.com/v1")),
            patch("app.gateway.ingestion_image.AsyncOpenAI", return_value=mock_client) as mock_cls,
        ):
            result = await describe(_fake_image, "trace-2")

        mock_cls.assert_called_once_with(
            api_key="test-key",
            base_url="https://custom.api.com/v1",
        )
        assert result.content == "描述結果"


class TestOcrFallback:
    @pytest.mark.asyncio
    async def test_ocr_when_no_api_key(self, _fake_image):
        with (
            patch("app.gateway.ingestion_image.get_tts_config", return_value=_vision_cfg(api_key="")),
            patch("app.gateway.ingestion_image._ocr_fallback", return_value="OCR文字") as mock_ocr,
        ):
            result = await describe(_fake_image, "trace-3")

        mock_ocr.assert_called_once_with(_fake_image, "trace-3")
        assert result.content == "OCR文字"

    @pytest.mark.asyncio
    async def test_ocr_when_vision_fails(self, _fake_image):
        with (
            patch("app.gateway.ingestion_image.get_tts_config", return_value=_vision_cfg()),
            patch("app.gateway.ingestion_image._describe_with_vision", new_callable=AsyncMock, side_effect=RuntimeError("API error")),
            patch("app.gateway.ingestion_image._ocr_fallback", return_value="OCR fallback"),
        ):
            result = await describe(_fake_image, "trace-4")

        assert result.content == "OCR fallback"


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_all_fail_returns_fallback_message(self, _fake_image):
        with (
            patch("app.gateway.ingestion_image.get_tts_config", return_value=_vision_cfg(api_key="")),
            patch("app.gateway.ingestion_image._ocr_fallback", side_effect=RuntimeError("OCR fail")),
        ):
            result = await describe(_fake_image, "trace-5")

        assert result.content_type == "image_description"
        assert "無法使用" in result.content

    @pytest.mark.asyncio
    async def test_empty_ocr_falls_through(self, _fake_image):
        with (
            patch("app.gateway.ingestion_image.get_tts_config", return_value=_vision_cfg(api_key="")),
            patch("app.gateway.ingestion_image._ocr_fallback", return_value=""),
        ):
            result = await describe(_fake_image, "trace-6")

        assert "無法使用" in result.content

"""Tests for audio ingestion."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gateway.ingestion_audio import transcribe


@pytest.fixture
def fake_audio(tmp_path):
    path = tmp_path / "test.mp3"
    path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 100)
    return str(path)


def _openai_cfg() -> MagicMock:
    return MagicMock(
        whisper_provider="openai",
        whisper_api_key="test-key",
        vision_llm_base_url="",
    )


def _local_cfg() -> MagicMock:
    return MagicMock(
        whisper_provider="local",
        whisper_local_bin="/usr/bin/whisper",
    )


class TestOpenAITranscription:
    @pytest.mark.asyncio
    async def test_openai_success(self, fake_audio):
        mock_response = MagicMock()
        mock_response.text = "你好世界"

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)

        with (
            patch("app.gateway.ingestion_audio.get_tts_config", return_value=_openai_cfg()),
            patch("app.gateway.ingestion_audio.AsyncOpenAI", return_value=mock_client),
        ):
            result = await transcribe(fake_audio, "trace-1")

        assert result.content_type == "audio_transcription"
        assert result.content == "你好世界"

    @pytest.mark.asyncio
    async def test_openai_failure_returns_fallback(self, fake_audio):
        with (
            patch("app.gateway.ingestion_audio.get_tts_config", return_value=_openai_cfg()),
            patch("app.gateway.ingestion_audio.AsyncOpenAI", side_effect=RuntimeError("API down")),
        ):
            result = await transcribe(fake_audio, "trace-2")

        assert "轉錄失敗" in result.content


class TestLocalTranscription:
    @pytest.mark.asyncio
    async def test_local_success_from_file(self, fake_audio, tmp_path):
        # whisper writes to <input>.txt
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("本地轉錄結果", encoding="utf-8")

        mock_result = MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch("app.gateway.ingestion_audio.get_tts_config", return_value=_local_cfg()),
            patch("app.gateway.ingestion_audio.subprocess.run", return_value=mock_result),
        ):
            result = await transcribe(fake_audio, "trace-3")

        assert result.content == "本地轉錄結果"

    @pytest.mark.asyncio
    async def test_local_success_from_stdout(self, fake_audio):
        mock_result = MagicMock(returncode=0, stdout="stdout轉錄", stderr="")

        with (
            patch("app.gateway.ingestion_audio.get_tts_config", return_value=_local_cfg()),
            patch("app.gateway.ingestion_audio.subprocess.run", return_value=mock_result),
        ):
            result = await transcribe(fake_audio, "trace-4")

        assert result.content == "stdout轉錄"

    @pytest.mark.asyncio
    async def test_local_nonzero_exit(self, fake_audio):
        mock_result = MagicMock(returncode=1, stderr="error")

        with (
            patch("app.gateway.ingestion_audio.get_tts_config", return_value=_local_cfg()),
            patch("app.gateway.ingestion_audio.subprocess.run", return_value=mock_result),
        ):
            result = await transcribe(fake_audio, "trace-5")

        assert "轉錄失敗" in result.content

"""Tests for video ingestion."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gateway.ingestion import IngestionResult
from app.gateway.ingestion_video import _extract_frames, describe


@pytest.fixture
def fake_video(tmp_path):
    path = tmp_path / "test.mp4"
    path.write_bytes(b"\x00" * 100)
    return str(path)


class TestExtractFrames:
    def test_success(self, tmp_path):
        output_dir = str(tmp_path / "frames")
        os.makedirs(output_dir)

        # Pre-create fake frame files
        for i in range(3):
            (tmp_path / "frames" / f"frame_{i + 1:04d}.jpg").write_bytes(b"\xff\xd8")

        mock_result = MagicMock(returncode=0)

        with patch("app.gateway.ingestion_video.subprocess.run", return_value=mock_result):
            frames = _extract_frames("/fake/video.mp4", output_dir)

        assert len(frames) == 3
        assert all("frame_" in f for f in frames)

    def test_ffmpeg_failure(self, tmp_path):
        mock_result = MagicMock(returncode=1, stderr="ffmpeg error")

        with patch("app.gateway.ingestion_video.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="ffmpeg failed"):
                _extract_frames("/fake/video.mp4", str(tmp_path))


class TestDescribe:
    @pytest.mark.asyncio
    async def test_success_multiple_frames(self, fake_video):
        fake_frames = ["/tmp/f1.jpg", "/tmp/f2.jpg"]

        async def mock_describe_image(path, trace_id):
            return IngestionResult(content_type="image_description", content=f"描述{path}")

        with (
            patch("app.gateway.ingestion_video._extract_frames", return_value=fake_frames),
            patch("app.gateway.ingestion_video.describe_image", side_effect=mock_describe_image),
            patch("app.gateway.ingestion_video.tempfile.mkdtemp", return_value="/tmp/fake-frames"),
            patch("app.gateway.ingestion_video.shutil.rmtree"),
        ):
            result = await describe(fake_video, "trace-1")

        assert result.content_type == "video_description"
        assert "[影格 1/2]" in result.content
        assert "[影格 2/2]" in result.content

    @pytest.mark.asyncio
    async def test_no_frames(self, fake_video):
        with (
            patch("app.gateway.ingestion_video._extract_frames", return_value=[]),
            patch("app.gateway.ingestion_video.tempfile.mkdtemp", return_value="/tmp/fake-frames"),
            patch("app.gateway.ingestion_video.shutil.rmtree"),
        ):
            result = await describe(fake_video, "trace-2")

        assert "無法提取" in result.content

    @pytest.mark.asyncio
    async def test_extraction_error(self, fake_video):
        with (
            patch("app.gateway.ingestion_video._extract_frames", side_effect=RuntimeError("boom")),
            patch("app.gateway.ingestion_video.tempfile.mkdtemp", return_value="/tmp/fake-frames"),
            patch("app.gateway.ingestion_video.shutil.rmtree"),
        ):
            result = await describe(fake_video, "trace-3")

        assert "無法使用" in result.content

    @pytest.mark.asyncio
    async def test_cleanup_always_runs(self, fake_video):
        with (
            patch("app.gateway.ingestion_video._extract_frames", side_effect=RuntimeError("boom")),
            patch("app.gateway.ingestion_video.tempfile.mkdtemp", return_value="/tmp/fake-frames"),
            patch("app.gateway.ingestion_video.shutil.rmtree") as mock_rm,
        ):
            await describe(fake_video, "trace-4")

        mock_rm.assert_called_once_with("/tmp/fake-frames", ignore_errors=True)

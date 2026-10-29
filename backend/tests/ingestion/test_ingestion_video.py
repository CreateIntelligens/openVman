"""Tests for video ingestion."""

from __future__ import annotations

import os
import shutil
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gateway.ingestion import IngestionResult
from app.gateway.ingestion_video import _extract_frames, describe
from app.utils.media import MediaProbe


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
            frames = _extract_frames("/fake/video.mp4", output_dir, 60)

        assert len(frames) == 3
        assert all("frame_" in f for f in frames)

    def test_ffmpeg_failure(self, tmp_path):
        mock_result = MagicMock(returncode=1, stderr="ffmpeg error")

        with patch("app.gateway.ingestion_video.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="ffmpeg failed"):
                _extract_frames("/fake/video.mp4", str(tmp_path), 60)


class TestFrameCap:
    """Every frame is one paid VLM call, so the count must stay bounded."""

    @staticmethod
    def _probe(seconds: float) -> MediaProbe:
        return MediaProbe("mov,mp4", seconds, has_audio=False, has_video=True)

    def _run(self, tmp_path, seconds: float, produced: int, max_frames: int = 60):
        output_dir = tmp_path / "frames"
        output_dir.mkdir()
        for i in range(produced):
            (output_dir / f"frame_{i + 1:04d}.jpg").write_bytes(b"\xff\xd8")
        with (
            patch("app.gateway.ingestion_video.probe_media", return_value=self._probe(seconds)),
            patch(
                "app.gateway.ingestion_video.subprocess.run",
                return_value=MagicMock(returncode=0),
            ) as run,
        ):
            frames = _extract_frames("/fake/video.mp4", str(output_dir), max_frames)
        return frames, run.call_args.args[0]

    def test_short_clip_keeps_one_frame_per_second(self, tmp_path):
        frames, args = self._run(tmp_path, seconds=30, produced=30)
        assert args[args.index("-vf") + 1] == "fps=1"
        assert args[args.index("-frames:v") + 1] == "60"
        assert len(frames) == 30

    def test_long_clip_is_sampled_evenly_down_to_the_cap(self, tmp_path):
        frames, args = self._run(tmp_path, seconds=120, produced=75)
        assert args[args.index("-vf") + 1] == "fps=60/120.000"
        assert len(frames) == 60

    @pytest.mark.asyncio
    async def test_describe_uses_configured_cap(self, fake_video, monkeypatch):
        monkeypatch.setenv("GATEWAY_VIDEO_MAX_FRAMES", "3")
        from app.config import get_tts_config

        get_tts_config.cache_clear()
        seen: list[int] = []

        def fake_extract(path, output_dir, max_frames):
            seen.append(max_frames)
            return [f"/tmp/f{i}.jpg" for i in range(max_frames)]

        describe_image = AsyncMock(
            return_value=IngestionResult(content_type="image_description", content="x"),
        )
        try:
            with (
                patch("app.gateway.ingestion_video._extract_frames", side_effect=fake_extract),
                patch("app.gateway.ingestion_video.describe_image", describe_image),
                patch("app.gateway.ingestion_video.shutil.rmtree"),
            ):
                await describe(fake_video, "trace-cap")
        finally:
            get_tts_config.cache_clear()
        assert seen == [3]
        assert describe_image.await_count == 3

    @pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
    def test_real_ffmpeg_respects_the_cap(self, tmp_path):
        clip = tmp_path / "clip.mp4"
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-f", "lavfi",
                "-i", "color=c=blue:s=32x32:d=6", "-pix_fmt", "yuv420p", str(clip),
            ],
            check=True,
            timeout=60,
        )
        output_dir = tmp_path / "frames"
        output_dir.mkdir()
        frames = _extract_frames(str(clip), str(output_dir), 3)
        assert 1 <= len(frames) <= 3


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

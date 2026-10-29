"""Video ingestion — ffmpeg frame extraction + per-frame image description."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import get_tts_config
from app.gateway.ingestion import IngestionResult
from app.gateway.ingestion_image import describe as describe_image
from app.utils.media import probe_media
from app.utils.upload import UnsupportedUploadError

logger = logging.getLogger("gateway.ingestion_video")


def _sampling_fps(duration_seconds: float | None, max_frames: int) -> str:
    """1 fps for short clips; longer clips are sampled evenly down to ``max_frames``."""
    if duration_seconds is None or duration_seconds <= max_frames:
        return "1"
    return f"{max_frames}/{duration_seconds:.3f}"


def _extract_frames(video_path: str, output_dir: str, max_frames: int) -> list[str]:
    """Extract at most ``max_frames`` frames using ffmpeg.

    Returns sorted list of frame file paths.
    """
    try:
        duration: float | None = probe_media(video_path).duration_seconds
    except UnsupportedUploadError:
        duration = None
    pattern = os.path.join(output_dir, "frame_%04d.jpg")
    result = subprocess.run(
        [
            "ffmpeg", "-i", video_path,
            "-vf", f"fps={_sampling_fps(duration, max_frames)}",
            "-frames:v", str(max_frames),
            "-q:v", "2",
            pattern,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[:500]}")

    frames = sorted(
        str(p) for p in Path(output_dir).glob("frame_*.jpg")
    )
    # 每張影格都要呼叫一次付費 VLM；ffmpeg 已限張數，這裡再保險截一次。
    return frames[:max_frames]


async def describe(file_path: str, trace_id: str) -> IngestionResult:
    """Describe a video by extracting frames and describing each.

    Returns IngestionResult with content_type="video_description".
    """
    logger.info("video_describe trace_id=%s path=%s", trace_id, file_path)
    frame_dir = tempfile.mkdtemp(prefix="vman-frames-")

    try:
        max_frames = get_tts_config().gateway_video_max_frames
        frames = _extract_frames(file_path, frame_dir, max_frames)
        if not frames:
            return IngestionResult(
                content_type="video_description",
                content="（影片無法提取影格）",
            )

        total = len(frames)
        logger.info("frames_extracted trace_id=%s count=%d", trace_id, total)

        descriptions: list[str] = []
        for idx, frame_path in enumerate(frames, start=1):
            result = await describe_image(frame_path, f"{trace_id}-f{idx}")
            descriptions.append(f"[影格 {idx}/{total}] {result.content}")

        content = "\n\n".join(descriptions)
        logger.info("video_describe_ok trace_id=%s frames=%d chars=%d", trace_id, total, len(content))

        return IngestionResult(
            content_type="video_description",
            content=content,
        )

    except Exception as exc:
        logger.error("video_describe_failed trace_id=%s err=%s", trace_id, exc)
        return IngestionResult(
            content_type="video_description",
            content="（影片描述服務暫時無法使用）",
        )

    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)

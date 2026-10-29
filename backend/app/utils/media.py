"""Probe uploaded audio/video with ffprobe before any paid engine sees it.

副檔名和 Content-Type 都是呼叫端說的；只有 ffprobe 讀得出容器與時長才算數。
"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass

from app.utils.upload import UnsupportedUploadError, UploadTooLargeError

PROBE_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class MediaProbe:
    format_name: str
    duration_seconds: float
    has_audio: bool
    has_video: bool


def probe_media(path: str) -> MediaProbe:
    """Return the real container format and duration, or raise 415."""
    try:
        completed = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=format_name,duration:stream=codec_type",
                "-of", "json", path,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        payload = json.loads(completed.stdout or "{}")
    except (OSError, subprocess.SubprocessError, TypeError, ValueError) as exc:
        raise UnsupportedUploadError("無法辨識的音訊或影片格式") from exc

    if not isinstance(payload, dict):
        raise UnsupportedUploadError("無法辨識的音訊或影片格式")
    fmt = payload.get("format") or {}
    stream_types = {
        str(stream.get("codec_type") or "")
        for stream in payload.get("streams") or []
    }
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = math.nan
    if not math.isfinite(duration) or duration <= 0:
        raise UnsupportedUploadError("無法讀取音訊或影片長度")
    if not stream_types & {"audio", "video"}:
        raise UnsupportedUploadError("檔案裡沒有音訊或影像")
    return MediaProbe(
        format_name=str(fmt.get("format_name") or ""),
        duration_seconds=duration,
        has_audio="audio" in stream_types,
        has_video="video" in stream_types,
    )


def require_duration(probe: MediaProbe, *, max_seconds: float, what: str) -> None:
    if probe.duration_seconds > max_seconds:
        raise UploadTooLargeError(
            0, f"{what}長度超過上限（{_format_seconds(max_seconds)}）",
        )


def _format_seconds(seconds: float) -> str:
    whole = int(seconds)
    if whole >= 60 and whole % 60 == 0:
        return f"{whole // 60} 分鐘"
    return f"{whole} 秒"

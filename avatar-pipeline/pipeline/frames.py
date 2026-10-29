"""Frame I/O for the bundle pipeline: alpha-aware intermediate and loop seam.

OpenCV's ``VideoCapture`` drops the alpha channel, so every pass reads the
intermediate through an ffmpeg rawvideo pipe instead. The intermediate is
FFV1 with every frame a keyframe: lossless, keeps alpha, and lets the
ping-pong step seek to any frame exactly.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

FPS = 25
#: Longest side the source is scaled down to; the renderer never needs more
#: and a phone's 4K upload would otherwise become a 4K VP9 bundle.
DEFAULT_MAX_SIDE = 1920
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
#: A still image becomes this many seconds of identical frames.
STILL_SECONDS = 10
#: Mean absolute difference (0–255) between the first and last frame above
#: which looping would visibly jump; a still or a clip that returns to its
#: starting pose stays well below it.
LOOP_SEAM_THRESHOLD = 6.0
#: Frames held in memory at once while writing the reversed half.
REVERSE_CHUNK = 25
_SEAM_PROBE_WIDTH = 64
#: Background used only for landmark detection behind transparent pixels.
DETECTION_BACKGROUND = 128

ProgressCallback = Callable[[int, int], None]


class VideoProcessingError(RuntimeError):
    """The source video cannot be turned into a bundle."""


@dataclass(frozen=True)
class SourceInfo:
    width: int
    height: int
    has_alpha: bool
    is_image: bool
    #: Decoder to force before ``-i``: ffmpeg's native VP8/VP9 decoders
    #: ignore the alpha side channel that WebM stores separately.
    decoder: str | None = None


_ALPHA_DECODERS = {"vp8": "libvpx", "vp9": "libvpx-vp9"}


def _ffprobe_stream(path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,pix_fmt,codec_name:stream_tags=alpha_mode",
        "-of", "json", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    streams = json.loads(result.stdout or "{}").get("streams") or []
    if result.returncode != 0 or not streams:
        raise VideoProcessingError("無法讀取影片或圖片")
    return streams[0]


def _pix_fmt_has_alpha(pix_fmt: str) -> bool:
    return pix_fmt.startswith(("yuva", "gbrap", "ya")) or pix_fmt in {
        "rgba", "bgra", "argb", "abgr", "rgba64le", "rgba64be", "pal8",
    }


def probe_source(path: Path) -> SourceInfo:
    stream = _ffprobe_stream(path)
    codec = stream.get("codec_name", "")
    tags = stream.get("tags") or {}
    webm_alpha = codec in {"vp8", "vp9"} and str(tags.get("alpha_mode", "")) == "1"
    return SourceInfo(
        width=int(stream["width"]),
        height=int(stream["height"]),
        has_alpha=webm_alpha or _pix_fmt_has_alpha(stream.get("pix_fmt", "")),
        is_image=path.suffix.lower() in IMAGE_SUFFIXES,
        decoder=_ALPHA_DECODERS[codec] if webm_alpha else None,
    )


def scaled_size(width: int, height: int, max_side: int) -> tuple[int, int]:
    """Both sides forced even: VP9 4:2:0 and MediaPipe crops need it."""
    scale = min(1.0, max_side / max(width, height))
    return int(width * scale) // 2 * 2, int(height * scale) // 2 * 2


#: 單一 ffmpeg 步驟的上限；正常素材幾十秒就完成，超過代表參數或輸入有問題。
STEP_TIMEOUT_SECONDS = 900


def _run(cmd: list[str], what: str) -> None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=STEP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise VideoProcessingError(f"{what}超過 {STEP_TIMEOUT_SECONDS} 秒未完成") from exc
    if result.returncode != 0:
        raise VideoProcessingError(f"{what}失敗：{result.stderr.strip()[-500:]}")


def _ffv1_output(path: Path) -> list[str]:
    return ["-c:v", "ffv1", "-g", "1", "-pix_fmt", "bgra", "-an", str(path)]


def prepare_video(
    input_path: Path, output_path: Path, *, max_side: int = DEFAULT_MAX_SIDE,
) -> SourceInfo:
    """Lossless 25 fps BGRA intermediate, scaled so the longest side ≤ ``max_side``."""
    info = probe_source(input_path)
    width, height = scaled_size(info.width, info.height, max_side)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if info.decoder:
        cmd += ["-c:v", info.decoder]
    video_filter = f"scale={width}:{height}"
    if info.is_image:
        # 圖片只解碼一次再用 loop 濾鏡複製。-loop 1 每輪重新解析檔案，
        # 帶 C2PA 或 IEND 後有多餘位元組的 PNG（AI 生成圖常見）會解不出下一格而永遠卡住。
        video_filter += f",loop=loop=-1:size=1,setpts=N/({FPS}*TB)"
    cmd += ["-i", str(input_path), "-vf", video_filter, "-r", str(FPS)]
    if info.is_image:
        cmd += ["-frames:v", str(STILL_SECONDS * FPS)]
    _run(cmd + _ffv1_output(output_path), "轉檔")
    return SourceInfo(width, height, info.has_alpha, info.is_image)


def read_frames(
    path: Path, width: int, height: int, *, start: int = 0, count: int | None = None,
) -> Iterator[np.ndarray]:
    """Yield ``(height, width, 4)`` BGRA frames from the intermediate."""
    cmd = ["ffmpeg", "-loglevel", "error"]
    if start:
        # Every FFV1 frame is a keyframe, so seeking lands exactly on ``start``.
        cmd += ["-ss", f"{start / FPS:.6f}"]
    cmd += ["-i", str(path)]
    if count is not None:
        cmd += ["-frames:v", str(count)]
    cmd += ["-f", "rawvideo", "-pix_fmt", "bgra", "-"]
    frame_bytes = width * height * 4
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    try:
        while True:
            chunk = proc.stdout.read(frame_bytes)
            if len(chunk) < frame_bytes:
                break
            yield np.frombuffer(chunk, np.uint8).reshape(height, width, 4)
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def count_frames(path: Path, width: int, height: int) -> int:
    return sum(1 for _ in read_frames(path, width, height))


def flatten_for_detection(frame: np.ndarray) -> np.ndarray:
    """BGR for MediaPipe: transparent pixels become a flat grey, not black noise."""
    bgr = frame[:, :, :3].astype(np.float32)
    alpha = frame[:, :, 3:4].astype(np.float32) / 255.0
    flat = bgr * alpha + DETECTION_BACKGROUND * (1.0 - alpha)
    return flat.astype(np.uint8)


def _seam_thumb(frame: np.ndarray) -> np.ndarray:
    flat = flatten_for_detection(frame)
    height = max(1, round(frame.shape[0] * _SEAM_PROBE_WIDTH / frame.shape[1]))
    small = cv2.resize(flat, (_SEAM_PROBE_WIDTH, height), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)


def loop_seam_difference(path: Path, width: int, height: int, frame_count: int) -> float:
    """Mean absolute grey difference between the first and the last frame."""
    first = next(read_frames(path, width, height, count=1))
    last = next(read_frames(path, width, height, start=frame_count - 1, count=1))
    return float(np.abs(_seam_thumb(first) - _seam_thumb(last)).mean())


def write_ping_pong(
    path: Path, output_path: Path, width: int, height: int, frame_count: int,
    *, progress: ProgressCallback | None = None,
) -> int:
    """Append the clip played backwards: 0…n-1 then n-2…1, so looping lands on 0.

    The reversed half is read in short chunks from the end so memory stays at
    ``REVERSE_CHUNK`` frames however long the clip is.
    """
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{width}x{height}",
        "-r", str(FPS), "-i", "-",
    ] + _ffv1_output(output_path)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    total = frame_count + max(frame_count - 2, 0)
    written = 0

    def emit(frame: np.ndarray) -> None:
        nonlocal written
        proc.stdin.write(frame.tobytes())
        written += 1
        if progress:
            progress(written, total)

    try:
        for frame in read_frames(path, width, height):
            emit(frame)
        # Reversed half covers frames n-2 down to 1.
        end = frame_count - 1
        while end > 1:
            start = max(1, end - REVERSE_CHUNK)
            chunk = list(read_frames(path, width, height, start=start, count=end - start))
            for frame in reversed(chunk):
                emit(frame)
            end = start
    finally:
        proc.stdin.close()
    stderr = proc.stderr.read().decode("utf-8", errors="ignore") if proc.stderr else ""
    proc.wait()
    if proc.returncode != 0:
        raise VideoProcessingError(f"首尾銜接失敗：{stderr.strip()[-500:]}")
    if written != total:
        raise VideoProcessingError(f"首尾銜接影格數不符：寫入 {written}、預期 {total}")
    return written

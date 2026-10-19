"""Turn a silent talking-head video into an avatar bundle.

A bundle is the pair the avatar runtime loads from ``data/avatar/<id>/``:

* ``01.webm`` — VP9, 25 fps, no audio, with a frame-sync marker in the
  top-right corner (``(frame % 7) * 40`` grey, 4×4 px) so the runtime can
  recover the exact frame index from the decoded picture.
* ``combined_data.json.gz`` — ``json_data`` holds one row per frame: a
  flattened 4×4 pose matrix followed by the 209 warp landmarks (x, y) in
  the 180-square; ``combined_data`` is the AES-128-CBC encrypted inner JSON
  with the face template, per-frame mouth crops and the frame count.
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .geometry import (
    INDEX_WRAP,
    MAIN_KEYPOINTS_INDEX,
    STANDARD_SIZE,
    crop_mouth,
    smooth_array,
    standardize_points,
)
from .landmarks import DEFAULT_MAX_SIDE, FPS, extract_landmarks, prepare_video

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
FACE_TEMPLATE_PATH = ASSETS_DIR / "face_template.json"
UID_PREFIX = "vman_"
KEY_BYTES = 16
MARKER_SIZE = 4
MARKER_LEVELS = 7
MARKER_STEP = 40

LANDMARK_SMOOTHING = [0.02, 0.09, 0.78, 0.09, 0.02]
CROP_CENTRE_SMOOTHING = [0.10, 0.20, 0.40, 0.20, 0.10]
POSE_SMOOTHING = [0.03, 0.1, 0.74, 0.1, 0.03]

#: ``(stage, done, total)``; ``total`` is 0 for stages without a frame count.
StageCallback = Callable[[str, int, int], None]


@dataclass(frozen=True)
class BundleResult:
    video_path: Path
    data_path: Path
    frame_count: int
    width: int
    height: int


class BundleKeyError(ValueError):
    """The bundle key is missing or the wrong length."""


def load_bundle_key(raw: str | None = None) -> bytes:
    value = raw if raw is not None else os.environ.get("AVATAR_BUNDLE_KEY", "")
    key = value.encode("utf-8")
    if len(key) != KEY_BYTES:
        raise BundleKeyError(
            f"AVATAR_BUNDLE_KEY 必須是 {KEY_BYTES} 個 ASCII 字元，目前是 {len(key)} 個"
        )
    return key


def load_face_template(path: Path = FACE_TEMPLATE_PATH) -> list[float]:
    with path.open("r", encoding="utf-8") as handle:
        template = json.load(handle)
    if len(template) % 3 != 0:
        raise ValueError("face template must be a flat list of xyz triples")
    return template


def encrypt_inner(key: bytes, payload: bytes) -> str:
    """Base64 of ``IV || AES-128-CBC(PKCS7(payload))`` as the runtime expects."""
    iv = os.urandom(KEY_BYTES)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(payload) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode("ascii")


def decrypt_inner(key: bytes, combined: str) -> bytes:
    raw = base64.b64decode(combined)
    iv, ciphertext = raw[:KEY_BYTES], raw[KEY_BYTES:]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def marker_value(frame_index: int) -> int:
    return (frame_index % MARKER_LEVELS) * MARKER_STEP


def stamp_marker(frame: np.ndarray, frame_index: int) -> None:
    """Paint the frame-sync marker in place on a BGR frame."""
    width = frame.shape[1]
    frame[0:MARKER_SIZE, width - MARKER_SIZE:width] = marker_value(frame_index)


def transcode_with_marker(
    source_path: Path, output_path: Path, *, progress: StageCallback | None = None,
) -> tuple[int, int, int]:
    """Pipe every frame through ffmpeg into VP9 with the marker stamped on."""
    cap = cv2.VideoCapture(str(source_path))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{width}x{height}", "-pix_fmt", "bgr24", "-r", str(FPS),
        "-i", "-",
        "-c:v", "libvpx-vp9", "-b:v", "500k", "-crf", "24",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-an",
        # Alt-ref frames are invisible frames; they would shift the frame
        # index the marker encodes.
        "-auto-alt-ref", "0",
        str(output_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    frame_index = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            stamp_marker(frame, frame_index)
            proc.stdin.write(frame.tobytes())
            frame_index += 1
            if progress:
                progress("transcode", frame_index, total)
    finally:
        cap.release()
        proc.stdin.close()
    stderr = proc.stderr.read().decode("utf-8", errors="ignore") if proc.stderr else ""
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg VP9 轉檔失敗：{stderr.strip()[-500:]}")
    return frame_index, width, height


def mouth_crops(pts_smooth: np.ndarray, width: int, height: int) -> np.ndarray:
    """One fixed-size square per frame, centred on the smoothed lip centre."""
    frame_count = len(pts_smooth)
    raw_rects = np.array([
        crop_mouth(pts[MAIN_KEYPOINTS_INDEX], width, height) for pts in pts_smooth
    ]).reshape(frame_count, -1)
    face_size = (
        (raw_rects[:, 2] - raw_rects[:, 0]).mean() / 2.0
        + (raw_rects[:, 3] - raw_rects[:, 1]).mean() / 2.0
    )
    face_size = int(face_size) // 2 * 2
    face_mid = (raw_rects[:, 2:] + raw_rects[:, 0:2]) / 2.0
    face_mid = smooth_array(face_mid, CROP_CENTRE_SMOOTHING).astype(int)
    return np.concatenate([face_mid - face_size // 2, face_mid + face_size // 2], axis=1)


def pose_rows(
    pts_smooth: np.ndarray, rects: np.ndarray, template: list[float],
) -> list[list[float]]:
    """Per-frame ``json_data`` rows: 16 pose values then 209 (x, y) pairs.

    The pose is the least-squares affine map taking the template's first 209
    vertices onto the frame's standardized warp landmarks; it absorbs the
    difference between the shared template and this person's face.
    """
    template_pts = np.array(template).reshape(-1, 3)
    template_h = np.hstack([template_pts[:len(INDEX_WRAP)], np.ones((len(INDEX_WRAP), 1))])
    standardized = [
        standardize_points(pts, rect, STANDARD_SIZE) for pts, rect in zip(pts_smooth, rects)
    ]
    mats = []
    for std_pts in standardized:
        target = std_pts[INDEX_WRAP]
        target_h = np.hstack([target, np.ones((len(INDEX_WRAP), 1))])
        mat, _, _, _ = np.linalg.lstsq(template_h, target_h, rcond=None)
        mats.append(mat)
    mats_smooth = smooth_array(np.array(mats).reshape(-1, 16), POSE_SMOOTHING)
    rows = []
    for std_pts, mat in zip(standardized, mats_smooth):
        warp_xy = std_pts[INDEX_WRAP, :2].flatten().tolist()
        rows.append([round(v, 5) for v in mat.tolist()] + [round(v, 1) for v in warp_xy])
    return rows


def build_bundle(
    input_video: Path,
    output_dir: Path,
    *,
    key: bytes,
    max_side: int = DEFAULT_MAX_SIDE,
    template_path: Path = FACE_TEMPLATE_PATH,
    progress: StageCallback | None = None,
) -> BundleResult:
    input_video = Path(input_video)
    output_dir = Path(output_dir)
    if not input_video.is_file():
        raise FileNotFoundError(f"找不到輸入影片：{input_video}")
    output_dir.mkdir(parents=True, exist_ok=True)
    template = load_face_template(template_path)

    def report(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    with tempfile.TemporaryDirectory(prefix="avatar-bundle-") as tmp:
        prepared = Path(tmp) / "prepared.mp4"
        report("prepare")
        prepare_video(input_video, prepared, max_side=max_side)

        report("landmarks")
        pts_3d = extract_landmarks(
            prepared, progress=lambda done, total: report("landmarks", done, total),
        )

        video_path = output_dir / "01.webm"
        frame_count, width, height = transcode_with_marker(
            prepared, video_path, progress=progress,
        )
        if frame_count != len(pts_3d):
            raise RuntimeError(
                f"影格數不一致：轉檔 {frame_count} 幀、特徵點 {len(pts_3d)} 幀"
            )

        report("geometry")
        pts_smooth = smooth_array(
            pts_3d.reshape(frame_count, -1), LANDMARK_SMOOTHING,
        ).reshape(frame_count, -1, 3)
        rects = mouth_crops(pts_smooth, width, height)
        rows = pose_rows(pts_smooth, rects, template)

        report("package")
        inner = {
            "uid": f"{UID_PREFIX}{uuid.uuid4()}",
            "frame_num": frame_count,
            "face3D_obj": template,
            "rect": rects.tolist(),
            "reverse_option": 0,
        }
        inner_bytes = json.dumps(inner, separators=(",", ":")).encode("utf-8")
        outer = {"combined_data": encrypt_inner(key, inner_bytes), "json_data": rows}
        data_path = output_dir / "combined_data.json.gz"
        tmp_data = data_path.with_suffix(".tmp")
        with gzip.open(tmp_data, "wt", encoding="utf-8") as handle:
            json.dump(outer, handle, separators=(",", ":"))
        shutil.move(tmp_data, data_path)

    return BundleResult(
        video_path=video_path,
        data_path=data_path,
        frame_count=frame_count,
        width=width,
        height=height,
    )

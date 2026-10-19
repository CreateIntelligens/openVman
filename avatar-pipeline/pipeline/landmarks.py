"""Silent-video preparation: 25 fps transcode and MediaPipe landmark extraction.

Ported from DH_live's ``data_preparation_mini`` (MIT licence). The detector
and mesh models are built once per video instead of once per frame.
"""

from __future__ import annotations

import math
import subprocess
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from .geometry import LANDMARK_COUNT

FPS = 25
#: Longest side the source is scaled down to; the renderer never needs more
#: and a phone's 4K upload would otherwise become a 4K VP9 bundle.
DEFAULT_MAX_SIDE = 1920
MIN_FACE_PIXELS = 80

ProgressCallback = Callable[[int, int], None]


class VideoProcessingError(RuntimeError):
    """The source video cannot be turned into a bundle."""


class FaceDetectionError(VideoProcessingError):
    """No usable single frontal face in the first frame."""


def probe_size(video_path: Path) -> tuple[int, int]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise VideoProcessingError("無法開啟影片檔")
    try:
        return (
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
    finally:
        cap.release()


def prepare_video(
    input_path: Path, output_path: Path, *, max_side: int = DEFAULT_MAX_SIDE,
) -> None:
    """Transcode to a silent 25 fps H.264 intermediate, scaled to ``max_side``.

    Both dimensions are forced even: libx264 refuses odd sizes and MediaPipe
    crops would otherwise drift by a pixel.
    """
    width, height = probe_size(input_path)
    scale = min(1.0, max_side / max(width, height))
    new_w = int(width * scale) // 2 * 2
    new_h = int(height * scale) // 2 * 2
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(input_path),
        "-vf", f"scale={new_w}:{new_h}",
        "-r", str(FPS), "-an",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise VideoProcessingError(f"ffmpeg 轉檔失敗：{result.stderr.strip()[-500:]}")


def _detect_face(face_detection, frame: np.ndarray, min_confidence: float) -> list[float]:
    """Relative ``[x_min, x_max, y_min, y_max]`` of the single frontal face."""
    import mediapipe as mp

    results = face_detection.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    if not results.detections:
        raise FaceDetectionError("第一幀偵測不到人臉")
    if len(results.detections) > 1:
        raise FaceDetectionError("第一幀偵測到多張人臉，影片裡只能有一個人")

    detection = results.detections[0]
    rect = detection.location_data.relative_bounding_box
    out_rect = [rect.xmin, rect.xmin + rect.width, rect.ymin, rect.ymin + rect.height]

    key_point = mp.solutions.face_detection.get_key_point
    points = mp.solutions.face_detection.FaceKeyPoint
    nose = key_point(detection, points.NOSE_TIP)
    left_eye = key_point(detection, points.LEFT_EYE)
    right_eye = key_point(detection, points.RIGHT_EYE)
    if nose.x > left_eye.x or nose.x < right_eye.x:
        raise FaceDetectionError("人臉角度太偏，請提供正面影片")

    h, w = frame.shape[:2]
    if out_rect[0] < 0 or out_rect[2] < 0 or out_rect[1] > 1 or out_rect[3] > 1:
        raise FaceDetectionError("人臉超出畫面邊界")
    if rect.width * w < MIN_FACE_PIXELS or rect.height * h < MIN_FACE_PIXELS:
        raise FaceDetectionError(f"人臉太小，至少要 {MIN_FACE_PIXELS}×{MIN_FACE_PIXELS} 像素")
    return out_rect


def _first_frame_face_rect(
    face_detection, frame: np.ndarray, vid_w: float, vid_h: float,
) -> tuple[int, int, int, int]:
    """Square crop around the face, padded so the mesh tracker has context."""
    try:
        rect = _detect_face(face_detection, frame, 0.25)
        x_min, y_min = int(rect[0] * vid_w), int(rect[2] * vid_h)
        x_max, y_max = int(rect[1] * vid_w), int(rect[3] * vid_h)
    except FaceDetectionError:
        # Retry on the central 80 %: a busy border sometimes fools the detector.
        cropped = frame[
            int(0.1 * vid_h):int(0.9 * vid_h), int(0.1 * vid_w):int(0.9 * vid_w),
        ]
        rect = _detect_face(face_detection, cropped, 0.25)
        x_min = int(rect[0] * vid_w + 0.1 * vid_w)
        y_min = int(rect[2] * vid_h + 0.1 * vid_h)
        x_max = int(rect[1] * vid_w + 0.1 * vid_w)
        y_max = int(rect[3] * vid_h + 0.1 * vid_h)

    x_mid, y_mid = (x_min + x_max) / 2.0, (y_min + y_max) / 2.0
    side = max(x_max - x_min, y_max - y_min)
    crop_size = int(side * 2 * 1.35)
    x0 = int(max(0, x_mid - crop_size * 0.5))
    y0 = int(max(0, y_mid - crop_size * 0.45))
    x1 = int(min(vid_w, x0 + crop_size))
    y1 = int(min(vid_h, y0 + crop_size))
    return x0, y0, x1, y1


def _mesh_points(face_mesh, frame: np.ndarray) -> np.ndarray:
    results = face_mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    if not results.multi_face_landmarks:
        raise VideoProcessingError("偵測不到面部網格")
    height, width = frame.shape[:2]
    pts = np.zeros((LANDMARK_COUNT, 3))
    for idx, landmark in enumerate(results.multi_face_landmarks[0].landmark):
        pts[idx] = [
            min(math.floor(landmark.x * width), width - 1),
            min(math.floor(landmark.y * height), height - 1),
            min(math.floor(landmark.z * width), width - 1),
        ]
    return pts


def extract_landmarks(
    video_path: Path, *, progress: ProgressCallback | None = None,
) -> np.ndarray:
    """478 × 3 pixel-space landmarks for every frame of a prepared video."""
    import mediapipe as mp

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise VideoProcessingError("無法開啟轉檔後的影片")
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        vid_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        vid_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        pts_3d = np.zeros((total, LANDMARK_COUNT, 3))
        face_rect: tuple[int, int, int, int] | None = None
        with mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.25,
        ) as face_detection, mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
        ) as face_mesh:
            for frame_index in range(total):
                ok, frame = cap.read()
                if not ok:
                    pts_3d = pts_3d[:frame_index]
                    break
                if face_rect is None:
                    face_rect = _first_frame_face_rect(face_detection, frame, vid_w, vid_h)
                x0, y0, x1, y1 = face_rect
                try:
                    pts_3d[frame_index] = _mesh_points(face_mesh, frame[y0:y1, x0:x1]) + [x0, y0, 0]
                except VideoProcessingError as exc:
                    raise VideoProcessingError(f"第 {frame_index} 幀{exc}") from exc
                if progress:
                    progress(frame_index + 1, total)
    finally:
        cap.release()
    if len(pts_3d) == 0:
        raise VideoProcessingError("影片沒有任何畫面")
    return pts_3d

"""MediaPipe landmark extraction over the prepared intermediate.

Ported from DH_live's ``data_preparation_mini`` (MIT licence). The detector
and mesh models are built once per video instead of once per frame.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from .frames import (
    DEFAULT_MAX_SIDE,
    FPS,
    VideoProcessingError,
    flatten_for_detection,
    read_frames,
)
from .geometry import LANDMARK_COUNT

__all__ = [
    "DEFAULT_MAX_SIDE",
    "FPS",
    "FaceDetectionError",
    "VideoProcessingError",
    "extract_landmarks",
]

MIN_FACE_PIXELS = 80

ProgressCallback = Callable[[int, int], None]


class FaceDetectionError(VideoProcessingError):
    """No usable single frontal face in the first frame."""


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
    video_path: Path, width: int, height: int, frame_count: int,
    *, progress: ProgressCallback | None = None,
) -> np.ndarray:
    """478 × 3 pixel-space landmarks for every frame of the intermediate."""
    import mediapipe as mp

    pts_3d = np.zeros((frame_count, LANDMARK_COUNT, 3))
    face_rect: tuple[int, int, int, int] | None = None
    read = 0
    with mp.solutions.face_detection.FaceDetection(
        model_selection=1, min_detection_confidence=0.25,
    ) as face_detection, mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
    ) as face_mesh:
        for frame_index, raw in enumerate(read_frames(video_path, width, height)):
            if frame_index >= frame_count:
                break
            frame = flatten_for_detection(raw)
            if face_rect is None:
                face_rect = _first_frame_face_rect(face_detection, frame, width, height)
            x0, y0, x1, y1 = face_rect
            try:
                pts_3d[frame_index] = _mesh_points(face_mesh, frame[y0:y1, x0:x1]) + [x0, y0, 0]
            except VideoProcessingError as exc:
                raise VideoProcessingError(f"第 {frame_index} 幀{exc}") from exc
            read = frame_index + 1
            if progress:
                progress(read, frame_count)
    if read == 0:
        raise VideoProcessingError("影片沒有任何畫面")
    return pts_3d[:read]

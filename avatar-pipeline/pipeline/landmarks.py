"""MediaPipe adapter with explicit frame, region and coordinate boundaries.

The former implementation was ported from DH_live (MIT). This replacement
calls the same installed MediaPipe Solutions API directly; historical model
settings, crop calibration and pixel quantization are retained in the
compatibility profile. Model/data provenance is not a clean-room claim.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .frames import (
    DEFAULT_MAX_SIDE,
    FPS,
    VideoProcessingError,
    flatten_for_detection,
    read_frames,
)
from .geometry import COMPATIBILITY_PROFILE, LANDMARK_COUNT

__all__ = [
    "DEFAULT_MAX_SIDE",
    "FPS",
    "FaceDetectionError",
    "VideoProcessingError",
    "extract_landmarks",
]

_DETECTION = COMPATIBILITY_PROFILE["detection"]
MIN_FACE_PIXELS = _DETECTION["min_face_pixels"]
ProgressCallback = Callable[[int, int], None]


class FaceDetectionError(VideoProcessingError):
    """No usable single frontal face in the first frame."""


def _positive_integer(value, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (int, np.integer),
    ) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _validate_frame(frame: np.ndarray, channels: int) -> None:
    if (
        not isinstance(frame, np.ndarray)
        or frame.ndim != 3
        or frame.shape[2] != channels
        or min(frame.shape[:2]) == 0
        or frame.dtype != np.uint8
    ):
        raise VideoProcessingError(
            f"影格必須是非空 uint8 陣列，通道數為 {channels}"
        )


def _rgb(frame: np.ndarray) -> np.ndarray:
    _validate_frame(frame, 3)
    return np.ascontiguousarray(frame[..., ::-1])


@dataclass(frozen=True)
class _Region:
    """Integer pixel bounds with a local-to-frame coordinate transform."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def size(self) -> np.ndarray:
        return np.array([self.right - self.left, self.bottom - self.top])

    def image(self, frame: np.ndarray) -> np.ndarray:
        if np.any(self.size <= 0):
            raise VideoProcessingError("人臉裁切區域為空")
        return frame[self.top:self.bottom, self.left:self.right]

    def relative_bounds(self, bounds: list[float]) -> np.ndarray:
        # Scale by the actual detector input, including a central retry ROI.
        corners = np.array(bounds).reshape(2, 2).T
        return np.trunc(
            corners * self.size + [self.left, self.top],
        ).astype(np.int64)

    def restore(self, points: np.ndarray) -> np.ndarray:
        return points + np.array([self.left, self.top, 0])


def _detect_face(
    face_detection, frame: np.ndarray, min_confidence: float,
) -> list[float]:
    """Validate the detector result and return [left, right, top, bottom]."""
    import mediapipe as mp

    if not np.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be between zero and one")
    result = face_detection.process(_rgb(frame))
    detections = result.detections or []
    if not detections:
        raise FaceDetectionError("第一幀偵測不到人臉")
    if len(detections) != 1:
        raise FaceDetectionError("第一幀偵測到多張人臉，影片裡只能有一個人")

    detection = detections[0]
    scores = np.asarray(detection.score, dtype=np.float64)
    if not scores.size or not np.isfinite(scores).all():
        raise FaceDetectionError("人臉偵測信心值無效")
    if scores[0] < min_confidence:
        raise FaceDetectionError("人臉偵測信心不足")
    rect = detection.location_data.relative_bounding_box
    bounds = np.array([
        [rect.xmin, rect.ymin],
        [rect.xmin + rect.width, rect.ymin + rect.height],
    ])
    if not np.isfinite(bounds).all() or np.any(bounds[1] <= bounds[0]):
        raise FaceDetectionError("人臉偵測範圍無效")
    if np.any(bounds < 0) or np.any(bounds > 1):
        raise FaceDetectionError("人臉超出畫面邊界")

    api = mp.solutions.face_detection
    nose = api.get_key_point(detection, api.FaceKeyPoint.NOSE_TIP)
    left = api.get_key_point(detection, api.FaceKeyPoint.LEFT_EYE)
    right = api.get_key_point(detection, api.FaceKeyPoint.RIGHT_EYE)
    positions = np.array([right.x, nose.x, left.x])
    if not np.isfinite(positions).all() or np.any(np.diff(positions) < 0):
        raise FaceDetectionError("人臉角度太偏，請提供正面影片")
    height, width = frame.shape[:2]
    if np.any((bounds[1] - bounds[0]) * [width, height] < MIN_FACE_PIXELS):
        raise FaceDetectionError(
            f"人臉太小，至少要 {MIN_FACE_PIXELS}×{MIN_FACE_PIXELS} 像素"
        )
    return bounds.T.reshape(4).tolist()


def _first_frame_face_rect(
    face_detection, frame: np.ndarray, vid_w: float, vid_h: float,
) -> tuple[int, int, int, int]:
    """Locate the face once and establish its mesh-processing context ROI."""
    _validate_frame(frame, 3)
    height, width = frame.shape[:2]
    if width != vid_w or height != vid_h:
        raise VideoProcessingError("第一幀尺寸與影片資訊不符")
    region = _Region(0, 0, width, height)
    try:
        detected = _detect_face(
            face_detection, frame, _DETECTION["min_confidence"],
        )
    except FaceDetectionError:
        inset = _DETECTION["retry_inset"]
        region = _Region(
            int(inset * width), int(inset * height),
            int((1 - inset) * width), int((1 - inset) * height),
        )
        detected = _detect_face(
            face_detection, region.image(frame),
            _DETECTION["min_confidence"],
        )
    bounds = region.relative_bounds(detected)
    centre = bounds.mean(axis=0)
    side = int((bounds[1] - bounds[0]).max() * _DETECTION["context_scale"])
    top_left = np.trunc(np.maximum(
        0, centre - side * np.array([
            0.5, _DETECTION["context_top_fraction"],
        ]),
    )).astype(np.int64)
    bottom_right = np.minimum(top_left + side, [width, height])
    if np.any(bottom_right <= top_left):
        raise FaceDetectionError("人臉裁切區域為空")
    return tuple(int(value) for value in np.concatenate((
        top_left, bottom_right,
    )))


def _mesh_points(face_mesh, frame: np.ndarray) -> np.ndarray:
    result = face_mesh.process(_rgb(frame))
    faces = result.multi_face_landmarks or []
    if not faces:
        raise VideoProcessingError("偵測不到面部網格")
    if len(faces) != 1:
        raise VideoProcessingError("面部網格必須只包含一張人臉")
    values = np.array([
        (point.x, point.y, point.z) for point in faces[0].landmark
    ], dtype=np.float64)
    if values.shape != (LANDMARK_COUNT, 3) or not np.isfinite(values).all():
        raise VideoProcessingError(
            f"面部網格必須包含 {LANDMARK_COUNT} 個有效 xyz 特徵點"
        )
    height, width = frame.shape[:2]
    # Preserve negative x/y and signed z: clipping them would change poses.
    return np.minimum(
        np.floor(values * [width, height, width]),
        np.array([width, height, width]) - 1,
    )


def extract_landmarks(
    video_path: Path, width: int, height: int, frame_count: int,
    *, progress: ProgressCallback | None = None,
) -> np.ndarray:
    """Extract up to frame_count frames as (frames, 478, 3) pixel coordinates.

    A shorter stream returns the frames actually read, allowing the bundle
    builder's count check to diagnose decoder disagreement. All MediaPipe
    resources and the frame iterator close on success or failure.
    """
    width = _positive_integer(width, "width")
    height = _positive_integer(height, "height")
    frame_count = _positive_integer(frame_count, "frame_count")

    import mediapipe as mp
    output = np.empty((frame_count, LANDMARK_COUNT, 3), dtype=np.float64)
    mesh_options = {
        name: value for name, value in COMPATIBILITY_PROFILE["mesh"].items()
        if name != "coordinates"
    }
    frames = read_frames(video_path, width, height)
    read = 0
    region = None
    try:
        with mp.solutions.face_detection.FaceDetection(
            model_selection=_DETECTION["model_selection"],
            min_detection_confidence=_DETECTION["min_confidence"],
        ) as detector, mp.solutions.face_mesh.FaceMesh(
            **mesh_options,
        ) as mesh:
            for index in range(frame_count):
                try:
                    raw = next(frames)
                except StopIteration:
                    break
                try:
                    _validate_frame(raw, 4)
                    if raw.shape[:2] != (height, width):
                        raise VideoProcessingError("影格尺寸與影片資訊不符")
                    frame = flatten_for_detection(raw)
                    if region is None:
                        region = _Region(*_first_frame_face_rect(
                            detector, frame, width, height,
                        ))
                    output[index] = region.restore(
                        _mesh_points(mesh, region.image(frame)),
                    )
                except FaceDetectionError:
                    raise
                except VideoProcessingError as exc:
                    raise VideoProcessingError(f"第 {index} 幀{exc}") from exc
                read += 1
                if progress:
                    progress(read, frame_count)
    finally:
        frames.close()
    if read == 0:
        raise VideoProcessingError("影片沒有任何畫面")
    return output[:read]

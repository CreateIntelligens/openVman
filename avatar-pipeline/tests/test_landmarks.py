"""Adapter contract tests independent of model inference and external data."""

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from pipeline import landmarks
from pipeline.geometry import LANDMARK_COUNT


def _face_api(monkeypatch):
    api = SimpleNamespace(
        FaceKeyPoint=SimpleNamespace(NOSE_TIP="nose", LEFT_EYE="left", RIGHT_EYE="right"),
        get_key_point=lambda detection, name: getattr(detection, name),
    )
    monkeypatch.setitem(sys.modules, "mediapipe", SimpleNamespace(
        solutions=SimpleNamespace(face_detection=api),
    ))
    return api


def _detection(**changes):
    values = dict(
        score=[0.9],
        location_data=SimpleNamespace(relative_bounding_box=SimpleNamespace(
            xmin=0.25, ymin=0.2, width=0.4, height=0.5,
        )),
        nose=SimpleNamespace(x=0.5),
        left=SimpleNamespace(x=0.6),
        right=SimpleNamespace(x=0.4),
    )
    values.update(changes)
    return SimpleNamespace(**values)


def _processor(**result):
    return SimpleNamespace(process=lambda rgb: SimpleNamespace(**result))


def test_detection_validates_rgb_conversion_and_face_bounds(monkeypatch):
    _face_api(monkeypatch)
    frame = np.zeros((400, 500, 3), dtype=np.uint8)
    frame[:] = [10, 20, 30]

    def process(rgb):
        assert rgb.flags.c_contiguous
        np.testing.assert_array_equal(rgb[0, 0], [30, 20, 10])
        return SimpleNamespace(detections=[_detection()])

    result = landmarks._detect_face(SimpleNamespace(process=process), frame, 0.25)
    np.testing.assert_allclose(result, [0.25, 0.65, 0.2, 0.7])


@pytest.mark.parametrize("detections", [
    [], [_detection(), _detection()], [_detection(score=[0.1])],
    [_detection(score=[np.nan])], [_detection(nose=SimpleNamespace(x=0.8))],
    [_detection(location_data=SimpleNamespace(relative_bounding_box=SimpleNamespace(
        xmin=-0.1, ymin=0.2, width=0.4, height=0.5,
    )))],
    [_detection(location_data=SimpleNamespace(relative_bounding_box=SimpleNamespace(
        xmin=0.2, ymin=0.2, width=0.1, height=0.5,
    )))],
])
def test_detection_rejects_unusable_faces(monkeypatch, detections):
    _face_api(monkeypatch)
    with pytest.raises(landmarks.FaceDetectionError):
        landmarks._detect_face(
            _processor(detections=detections),
            np.zeros((400, 500, 3), dtype=np.uint8), 0.25,
        )


def test_retry_coordinates_use_actual_central_detector_frame(monkeypatch):
    calls = []

    def detect(detector, frame, confidence):
        calls.append(frame.shape)
        if len(calls) == 1:
            raise landmarks.FaceDetectionError("retry")
        return [0.25, 0.75, 0.25, 0.75]

    monkeypatch.setattr(landmarks, "_detect_face", detect)
    result = landmarks._first_frame_face_rect(
        object(), np.zeros((400, 600, 3), dtype=np.uint8), 600, 400,
    )
    # Retry detector sees x=60..540/y=40..360. Its face is x=180..420,
    # y=120..280, centred on (300, 200), giving a 648-pixel context ROI.
    assert calls == [(400, 600, 3), (320, 480, 3)]
    assert result == (0, 0, 600, 400)


def test_retry_coordinates_preserve_small_offcentre_face(monkeypatch):
    count = 0

    def detect(*args):
        nonlocal count
        count += 1
        if count == 1:
            raise landmarks.FaceDetectionError("retry")
        return [0.5, 0.7, 0.4, 0.6]

    monkeypatch.setattr(landmarks, "_detect_face", detect)
    actual = landmarks._first_frame_face_rect(
        object(), np.zeros((1000, 1000, 3), dtype=np.uint8), 1000, 1000,
    )
    assert actual == (364, 305, 796, 737)


def test_mesh_pixel_mapping_preserves_negative_depth_and_upper_clamp():
    point = SimpleNamespace(x=-0.1, y=1.1, z=-0.2)
    mesh = _processor(multi_face_landmarks=[SimpleNamespace(
        landmark=[point] * LANDMARK_COUNT,
    )])
    actual = landmarks._mesh_points(mesh, np.zeros((50, 100, 3), dtype=np.uint8))
    assert actual.shape == (LANDMARK_COUNT, 3)
    np.testing.assert_array_equal(actual[0], [-10, 49, -20])


@pytest.mark.parametrize("faces", [[], [SimpleNamespace(landmark=[])], [
    SimpleNamespace(landmark=[SimpleNamespace(x=np.nan, y=0, z=0)] * LANDMARK_COUNT),
]])
def test_mesh_rejects_missing_or_invalid_landmarks(faces):
    with pytest.raises(landmarks.VideoProcessingError):
        landmarks._mesh_points(
            _processor(multi_face_landmarks=faces),
            np.zeros((50, 100, 3), dtype=np.uint8),
        )


class _Session:
    def __init__(self):
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


def _extraction_setup(monkeypatch, frames):
    detector = _Session()
    mesh = _Session()
    options = {}

    def create(name, session):
        def factory(**kwargs):
            options[name] = kwargs
            return session
        return factory

    monkeypatch.setitem(sys.modules, "mediapipe", SimpleNamespace(solutions=SimpleNamespace(
        face_detection=SimpleNamespace(FaceDetection=create("detector", detector)),
        face_mesh=SimpleNamespace(FaceMesh=create("mesh", mesh)),
    )))
    state = {"closed": False}

    def read(*args):
        try:
            yield from frames
        finally:
            state["closed"] = True

    monkeypatch.setattr(landmarks, "read_frames", read)
    monkeypatch.setattr(landmarks, "_first_frame_face_rect", lambda *args: (10, 20, 90, 80))
    monkeypatch.setattr(landmarks, "_mesh_points", lambda *args: np.zeros((LANDMARK_COUNT, 3)))
    return detector, mesh, options, state


def test_extraction_restores_roi_origin_progress_and_closes_resources(monkeypatch, tmp_path):
    sessions = _extraction_setup(monkeypatch, [np.zeros((100, 100, 4), dtype=np.uint8)] * 3)
    progress = []
    actual = landmarks.extract_landmarks(
        tmp_path / "video.mkv", 100, 100, 2,
        progress=lambda done, total: progress.append((done, total)),
    )
    assert actual.shape == (2, LANDMARK_COUNT, 3)
    np.testing.assert_array_equal(actual[0, 0], [10, 20, 0])
    assert progress == [(1, 2), (2, 2)]
    detector, mesh, options, state = sessions
    assert detector.closed and mesh.closed and state["closed"]
    assert options == {
        "detector": {"model_selection": 1, "min_detection_confidence": 0.25},
        "mesh": {"static_image_mode": True, "max_num_faces": 1,
                 "refine_landmarks": True, "min_detection_confidence": 0.5},
    }


def test_extraction_short_input_returns_only_real_frames(monkeypatch, tmp_path):
    _extraction_setup(monkeypatch, [np.zeros((100, 100, 4), dtype=np.uint8)])
    assert len(landmarks.extract_landmarks(tmp_path / "video.mkv", 100, 100, 3)) == 1


def test_extraction_empty_input_fails_and_closes_models(monkeypatch, tmp_path):
    detector, mesh, _, _ = _extraction_setup(monkeypatch, [])
    with pytest.raises(landmarks.VideoProcessingError, match="沒有任何畫面"):
        landmarks.extract_landmarks(tmp_path / "video.mkv", 100, 100, 3)
    assert detector.closed and mesh.closed


def test_extraction_invalid_frame_fails_with_index_and_closes_resources(monkeypatch, tmp_path):
    detector, mesh, _, state = _extraction_setup(monkeypatch, [
        np.zeros((100, 100, 4), dtype=np.uint8),
        np.zeros((50, 100, 4), dtype=np.uint8),
    ])
    with pytest.raises(landmarks.VideoProcessingError, match="第 1 幀"):
        landmarks.extract_landmarks(tmp_path / "video.mkv", 100, 100, 3)
    assert detector.closed and mesh.closed and state["closed"]


@pytest.mark.parametrize("width,height,count", [(0, 100, 2), (100, -1, 2), (100, 100, 0), (100.5, 100, 2)])
def test_extraction_rejects_invalid_stream_metadata(monkeypatch, tmp_path, width, height, count):
    _extraction_setup(monkeypatch, [])
    with pytest.raises(ValueError):
        landmarks.extract_landmarks(tmp_path / "video.mkv", width, height, count)

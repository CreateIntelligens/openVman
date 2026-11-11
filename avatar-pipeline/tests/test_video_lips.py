"""Measured geometry validation, reproducibility and source independence."""

import gzip
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from pipeline import video_lips


@pytest.fixture
def landmarks():
    values = np.zeros((468, 2), dtype=float)
    angle = np.arange(20) * np.pi / 10 + np.pi
    values[list(video_lips.OUTER_LIP)] = np.column_stack([
        160 + 30 * np.cos(angle), 120 - 10 * np.sin(angle),
    ])
    values[list(video_lips.INNER_LIP)] = np.column_stack([
        160 + 25 * np.cos(angle), 120 - 4 * np.sin(angle),
    ])
    return values


def test_contours_preserve_fractional_positions_and_square_bounds(landmarks):
    landmarks += 0.123456789
    frame = video_lips.contours_from_landmarks(landmarks, 320, 240)
    left, top, right, bottom = frame["region"]
    assert right - left == pytest.approx(bottom - top)
    assert len(frame["outer"]) == len(frame["inner"]) == 40
    restored = np.array(frame["outer"]).reshape(20, 2)
    restored = restored * (right - left) / 180 + [left, top]
    np.testing.assert_allclose(restored, landmarks[list(video_lips.OUTER_LIP)])
    assert not np.equal(np.floor(restored), restored).all()
    assert set(frame) == {"region", "outer", "inner"}


@pytest.mark.parametrize("shape", [(0, 2), (468, 3), (415, 2), (936,)])
def test_bad_landmark_layout_is_rejected(shape):
    with pytest.raises(ValueError):
        video_lips.contours_from_landmarks(np.zeros(shape), 320, 240)


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_nonfinite_landmarks_are_rejected(landmarks, bad):
    landmarks[61, 0] = bad
    with pytest.raises(ValueError):
        video_lips.contours_from_landmarks(landmarks, 320, 240)


def test_degenerate_mouth_is_rejected(landmarks):
    landmarks[291] = landmarks[61]
    with pytest.raises(ValueError, match="Degenerate"):
        video_lips.contours_from_landmarks(landmarks, 320, 240)


def test_edge_crop_remains_square_and_inside_video(landmarks):
    landmarks[:, 0] -= 120
    frame = video_lips.contours_from_landmarks(landmarks, 320, 240)
    left, top, right, bottom = frame["region"]
    assert left == 0
    assert 0 <= top < bottom <= 240
    assert right - left == pytest.approx(bottom - top)


def test_alpha_flattening_uses_neutral_background_and_preserves_opaque_pixels():
    pixels = np.array([[
        [255, 0, 33, 0], [20, 100, 240, 255], [255, 255, 255, 128],
    ]], dtype=np.uint8)
    result = video_lips._flatten_rgba(pixels)
    assert result.tolist() == [[[128, 128, 128], [20, 100, 240], [192, 192, 192]]]


def test_alpha_webm_forces_decoder_before_input_and_feeds_flattened_rgb(monkeypatch):
    monkeypatch.setattr(video_lips, "_video_stream", lambda *args: {
        "codec_name": "vp9", "tags": {"alpha_mode": "1"},
    })

    class Process:
        def __init__(self, command, **kwargs):
            assert command.index("libvpx-vp9") < command.index("-i")
            assert command[command.index("-pix_fmt") + 1] == "rgba"
            self.stdout = io.BytesIO(bytes([255, 0, 10, 0, 20, 100, 240, 255]))

        def wait(self):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(video_lips.subprocess, "Popen", Process)
    actual = list(video_lips._rgb_frames(Path("alpha.webm"), 2, 1))
    assert len(actual) == 1
    assert actual[0].tolist() == [[[128, 128, 128], [20, 100, 240]]]


def test_gzip_encoding_is_deterministic_and_failed_encoding_preserves_previous(tmp_path):
    output = tmp_path / "render_data.json.gz"
    payload = {"schema": "openvman.render.v2", "frames": [0.123456789]}
    video_lips.write_video_lips(output, payload)
    before = output.read_bytes()
    video_lips.write_video_lips(output, payload)
    assert output.read_bytes() == before
    assert json.loads(gzip.decompress(before)) == payload
    with pytest.raises(ValueError):
        video_lips.write_video_lips(output, {"frames": [float("nan")]})
    assert output.read_bytes() == before


def test_sidecar_permissions_are_readable_by_other_service_users(tmp_path):
    output = tmp_path / "render_data.json.gz"
    video_lips.write_video_lips(output, {"schema": "openvman.render.v2"})
    assert output.stat().st_mode & 0o777 == 0o644
    output.chmod(0o600)
    video_lips.write_video_lips(output, {"schema": "openvman.render.v2"})
    assert output.stat().st_mode & 0o777 == 0o644


def _roi_detector_fixture(*, local_face=True, detected_face=True):
    events = []
    normalized = np.tile([0.25, 0.75], (468, 1))
    normalized[1] = [0.2, 0.3]
    normalized[2] = [0.8, 0.7]
    points = [SimpleNamespace(x=x, y=y) for x, y in normalized]

    class Mesh:
        count = 0

        def __init__(self, **options):
            self.name = "full" if self.count == 0 else "local"
            Mesh.count += 1

        def __enter__(self):
            events.append(("enter", self.name))
            return self

        def __exit__(self, *args):
            events.append(("close", self.name))

        def process(self, rgb):
            events.append(("process", self.name, rgb.shape[:2]))
            faces = [SimpleNamespace(landmark=points)]
            if self.name == "full" or not local_face:
                faces = []
            return SimpleNamespace(multi_face_landmarks=faces)

    class LongRange:
        def __init__(self, **options):
            assert options["model_selection"] == 1

        def __enter__(self):
            events.append(("enter", "long"))
            return self

        def __exit__(self, *args):
            events.append(("close", "long"))

        def process(self, rgb):
            rect = SimpleNamespace(xmin=0.4, ymin=0.2, width=0.2, height=0.3)
            face = SimpleNamespace(location_data=SimpleNamespace(
                relative_bounding_box=rect,
            ))
            return SimpleNamespace(detections=[face] if detected_face else [])

    mp = SimpleNamespace(solutions=SimpleNamespace(
        face_mesh=SimpleNamespace(FaceMesh=Mesh),
        face_detection=SimpleNamespace(FaceDetection=LongRange),
    ))
    return mp, events


def test_long_range_roi_restores_original_xy_and_closes_all_graphs():
    mp, events = _roi_detector_fixture()
    tracking = {"fullFrameFrames": 0, "roiFrames": 0, "relocations": 0}
    frames = iter([np.zeros((240, 320, 3), np.uint8)])
    points = list(video_lips._tracked_landmarks(mp, frames, 320, 240, tracking))
    # Normalized box [0.4,0.2,0.2,0.3] -> [128,48,192,120], with
    # an independently padded 108-square ROI starting at [106,30].
    np.testing.assert_allclose(points[0][0], [133, 111])
    assert ("process", "local", (108, 108)) in events
    assert tracking == {"fullFrameFrames": 0, "roiFrames": 1, "relocations": 1}
    assert events[-3:] == [("close", "local"), ("close", "long"), ("close", "full")]


@pytest.mark.parametrize("local_face,detected_face", [(False, True), (True, False)])
def test_roi_failure_stays_fail_closed_and_releases_all_graphs(
    local_face, detected_face,
):
    mp, events = _roi_detector_fixture(
        local_face=local_face, detected_face=detected_face,
    )
    tracking = {"fullFrameFrames": 0, "roiFrames": 0, "relocations": 0}
    frames = iter([np.zeros((240, 320, 3), np.uint8)])
    with pytest.raises(ValueError):
        list(video_lips._tracked_landmarks(mp, frames, 320, 240, tracking))
    assert events[-3:] == [("close", "local"), ("close", "long"), ("close", "full")]
    assert tracking["roiFrames"] == 0


def test_generator_reads_only_video_detector_and_own_implementation(
    tmp_path, monkeypatch, landmarks,
):
    video = tmp_path / "01.webm"
    video.write_bytes(b"own-video")
    normalized = [
        SimpleNamespace(x=point[0] / 320, y=point[1] / 240)
        for point in landmarks
    ]

    class Detector:
        def __init__(self, **options):
            assert options["refine_landmarks"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def process(self, rgb):
            return SimpleNamespace(multi_face_landmarks=[
                SimpleNamespace(landmark=normalized),
            ])

    mp = SimpleNamespace(solutions=SimpleNamespace(
        face_mesh=SimpleNamespace(FaceMesh=Detector),
    ))
    monkeypatch.setitem(sys.modules, "mediapipe", mp)
    monkeypatch.setattr(video_lips, "_video_dimensions", lambda *args: (320, 240))
    monkeypatch.setattr(video_lips, "_rgb_frames", lambda *args: iter([
        np.zeros((240, 320, 3), dtype=np.uint8),
    ]))
    monkeypatch.setattr(video_lips, "_detector_provenance", lambda mp: {"package": "mediapipe"})
    payload = video_lips.generate_video_lips(video)
    assert payload["schema"] == "openvman.render.v2"
    assert payload["geometrySource"] == "mediapipe-video"
    assert len(payload["frames"]) == 1
    assert payload["provenance"]["videoSha256"] == video_lips.sha256_file(video)
    assert payload["provenance"]["inputs"] == ["input-video", "MediaPipe FaceMesh"]
    assert "template" not in payload


def test_production_cli_imports_without_historical_modules_or_assets(tmp_path):
    package = tmp_path / "pipeline"
    package.mkdir()
    source = Path(video_lips.__file__).parent
    for name in ("__init__.py", "bundle.py", "cli.py", "frames.py", "video_lips.py"):
        shutil.copy2(source / name, package / name)
    probe = (
        "import sys; import pipeline.cli; "
        "assert 'pipeline.geometry' not in sys.modules; "
        "assert 'pipeline.landmarks' not in sys.modules; "
        "assert 'pipeline.render_data' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

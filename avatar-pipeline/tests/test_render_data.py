"""Portable render format, producer validation and legacy bundle preservation."""

import copy
import gzip
import json
from pathlib import Path

import numpy as np
import pytest

from pipeline import bundle
from pipeline.frames import SourceInfo
from pipeline.geometry import LANDMARK_COUNT
from pipeline.render_data import render_data, write_render_data

KEY = b"0123456789abcdef"


@pytest.fixture
def geometry():
    matrix = [2, 3, 5, 0, 7, 11, 13, 0, 17, 19, 23, 0, 29, 31, 37, 1]
    translated_identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -4, 6, 0, 1]
    warp = (np.arange(418) * 0.1).tolist()
    return {
        "rows": [matrix + warp, translated_identity + warp],
        "rectangles": [[10, 20, 190, 200], [12, 22, 192, 202]],
        "template": np.arange(1395, dtype=float).tolist(),
        "width": 320,
        "height": 240,
    }


def test_render_rows_preserve_legacy_prefix_and_use_row_vector_affine(geometry):
    before = copy.deepcopy(geometry)
    payload = render_data(**geometry)
    assert payload["schema"] == "openvman.render.v1"
    assert payload["frameRate"] == 25
    assert payload["frameSize"] == [320, 240]
    assert payload["denseReference"] == "affine-rest"
    assert payload["template"] == geometry["template"]
    assert len(payload["frames"]) == 2
    for index, frame in enumerate(payload["frames"]):
        assert len(frame) == 950
        assert frame[:434] == geometry["rows"][index]
        assert frame[434:438] == geometry["rectangles"][index]
    # Template point 209 is (627, 628, 629). Row-vector multiplication
    # includes cross-coordinate terms and the final matrix row's translation.
    assert payload["frames"][0][438:440] == [16372, 20771]
    assert payload["frames"][1][438:440] == [623, 634]
    last_x, last_y, last_z = geometry["template"][-3:]
    assert payload["frames"][0][-2:] == [
        2 * last_x + 7 * last_y + 17 * last_z + 29,
        3 * last_x + 11 * last_y + 19 * last_z + 31,
    ]
    assert geometry == before


@pytest.mark.parametrize("field,value", [
    ("rows", []),
    ("rows", [[0] * 433]),
    ("rows", [[0] * 435]),
    ("rectangles", [[0, 0, 180, 180]]),
    ("rectangles", [[0, 0, 180], [0, 0, 180]]),
    ("template", [0] * 1394),
    ("template", [[0, 0, 0]] * 465),
])
def test_invalid_geometry_shape_is_rejected(geometry, field, value):
    geometry[field] = value
    with pytest.raises(ValueError):
        render_data(**geometry)


@pytest.mark.parametrize("field", ["rows", "rectangles", "template"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_inputs_are_rejected(geometry, field, value):
    if field == "template":
        geometry[field][0] = value
    else:
        geometry[field][0][0] = value
    with pytest.raises(ValueError):
        render_data(**geometry)


@pytest.mark.parametrize("rect", [
    [10, 20, 10, 200], [190, 20, 10, 200],
    [10, 20, 190, 20], [10, 200, 190, 20],
])
def test_empty_or_reversed_crop_is_rejected(geometry, rect):
    geometry["rectangles"][0] = rect
    with pytest.raises(ValueError):
        render_data(**geometry)


@pytest.mark.parametrize("dimension", ["width", "height"])
@pytest.mark.parametrize("value", [0, -1, 8193, float("nan"), float("inf"), True, 1.5, 320.0])
def test_invalid_frame_dimensions_are_rejected(geometry, dimension, value):
    geometry[dimension] = value
    with pytest.raises(ValueError):
        render_data(**geometry)


def test_maximum_supported_frame_side_is_accepted(geometry):
    geometry["width"] = 8192
    geometry["height"] = 8192
    assert render_data(**geometry)["frameSize"] == [8192, 8192]


def test_nonfinite_projected_coordinates_are_rejected(geometry):
    geometry["template"][209 * 3] = np.finfo(np.float64).max
    with np.errstate(over="ignore", invalid="ignore"), pytest.raises(ValueError):
        render_data(**geometry)


def test_gzip_writer_publishes_complete_payload_and_preserves_sources(
    geometry, tmp_path, monkeypatch,
):
    originals = {
        "01.webm": b"existing-video",
        "combined_data.json.gz": gzip.compress(b'{"existing":true}'),
    }
    for filename, data in originals.items():
        (tmp_path / filename).write_bytes(data)
    expected = render_data(**geometry)
    target = tmp_path / "render_data.json.gz"
    target.write_bytes(b"previous-sidecar")
    replace = Path.replace
    publications = []

    def inspect(temporary, destination):
        assert destination == target
        assert target.read_bytes() == b"previous-sidecar"
        assert json.loads(gzip.decompress(temporary.read_bytes())) == expected
        publications.append(True)
        return replace(temporary, destination)

    monkeypatch.setattr(Path, "replace", inspect)
    actual = write_render_data(target, **geometry)
    assert actual == target
    assert publications == [True]
    assert json.loads(gzip.decompress(target.read_bytes())) == expected
    assert not target.with_suffix(".tmp").exists()
    for filename, original in originals.items():
        assert (tmp_path / filename).read_bytes() == original


def test_invalid_geometry_cannot_replace_existing_sidecar(geometry, tmp_path):
    target = tmp_path / "render_data.json.gz"
    target.write_bytes(b"existing")
    geometry["rows"] = []
    with pytest.raises(ValueError):
        write_render_data(target, **geometry)
    assert target.read_bytes() == b"existing"
    assert list(tmp_path.glob("*.tmp")) == []


def test_bundle_defaults_to_video_measured_geometry_without_legacy_assets(
    tmp_path, monkeypatch,
):
    source = tmp_path / "source.webm"
    source.write_bytes(b"source-video")
    output = tmp_path / "result"
    payload = {
        "schema": "openvman.render.v2", "frameRate": 25,
        "frameSize": [320, 240], "geometrySource": "mediapipe-video",
        "frames": [{"region": [1, 2, 101, 102],
                    "outer": [90.0] * 40, "inner": [90.0] * 40}] * 2,
        "provenance": {"videoSha256": "a" * 64},
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("Default v2 builder touched a legacy asset")

    monkeypatch.setattr(bundle, "load_face_template", forbidden)
    monkeypatch.setattr(bundle, "pose_rows", forbidden)
    monkeypatch.setattr(bundle, "mouth_crops", forbidden)
    monkeypatch.setattr(bundle, "encrypt_inner", forbidden)
    monkeypatch.setattr(bundle, "prepare_video", lambda *a, **k: SourceInfo(320, 240, False, False))
    monkeypatch.setattr(bundle, "count_frames", lambda *a: 2)
    monkeypatch.setattr(bundle, "loop_seam_difference", lambda *a: 0.0)

    def measured(video, **kwargs):
        assert video == output / "01.webm"
        assert video.read_bytes() == b"produced-video"
        return payload

    monkeypatch.setattr(bundle, "generate_video_lips", measured)

    def transcode(source_path, output_path, *args, **kwargs):
        output_path.write_bytes(b"produced-video")
        return 2

    monkeypatch.setattr(bundle, "transcode_with_marker", transcode)
    result = bundle.build_bundle(source, output, loop_mode="off")
    outer = json.loads(gzip.decompress(result.data_path.read_bytes()))
    sidecar = json.loads(gzip.decompress((output / "render_data.json.gz").read_bytes()))
    assert outer == {"render_data": payload}
    assert sidecar == payload
    assert "template" not in sidecar
    assert result.video_path.read_bytes() == b"produced-video"
    assert source.read_bytes() == b"source-video"

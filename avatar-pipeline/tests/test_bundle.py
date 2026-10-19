import json

import numpy as np
import pytest

from pipeline import bundle
from pipeline.geometry import INDEX_WRAP, LANDMARK_COUNT

KEY = b"0123456789abcdef"


def test_encrypt_decrypt_roundtrip():
    payload = json.dumps({"uid": "vman_x", "frame_num": 3}).encode()
    combined = bundle.encrypt_inner(KEY, payload)
    assert bundle.decrypt_inner(KEY, combined) == payload


def test_bundle_key_must_be_16_ascii_bytes(monkeypatch):
    monkeypatch.setenv("AVATAR_BUNDLE_KEY", "short")
    with pytest.raises(bundle.BundleKeyError):
        bundle.load_bundle_key()
    assert bundle.load_bundle_key("0123456789abcdef") == KEY


def test_face_template_asset_is_465_points():
    template = bundle.load_face_template()
    assert len(template) == 465 * 3


def test_marker_cycles_through_seven_grey_levels():
    assert [bundle.marker_value(i) for i in range(8)] == [0, 40, 80, 120, 160, 200, 240, 0]
    frame = np.full((8, 8, 3), 255, dtype=np.uint8)
    bundle.stamp_marker(frame, 2)
    assert (frame[0:4, 4:8] == 80).all()
    assert (frame[4:, :] == 255).all() and (frame[:, :4] == 255).all()


def test_pose_rows_have_16_pose_values_and_209_points():
    rng = np.random.default_rng(0)
    frames = 6
    pts = rng.uniform(100, 300, size=(frames, LANDMARK_COUNT, 3))
    rects = np.tile(np.array([100, 100, 300, 300]), (frames, 1))
    rows = bundle.pose_rows(pts, rects, bundle.load_face_template())
    assert len(rows) == frames
    assert all(len(row) == 16 + 2 * len(INDEX_WRAP) for row in rows)


def test_mouth_crops_are_square_and_same_size_every_frame():
    rng = np.random.default_rng(1)
    pts = rng.uniform(200, 400, size=(7, LANDMARK_COUNT, 3))
    rects = bundle.mouth_crops(pts, width=720, height=1280)
    widths = rects[:, 2] - rects[:, 0]
    heights = rects[:, 3] - rects[:, 1]
    assert (widths == widths[0]).all()
    assert (heights == widths).all()

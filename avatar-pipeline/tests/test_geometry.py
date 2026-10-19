import numpy as np
import pytest

from pipeline.geometry import (
    INDEX_WRAP,
    LANDMARK_COUNT,
    MAIN_KEYPOINTS_INDEX,
    STANDARD_SIZE,
    SUBSET_FACE_OVAL,
    SUBSET_LIPS_OUTER,
    crop_mouth,
    smooth_array,
    standardize_points,
)


def test_index_tables_have_expected_sizes():
    assert len(INDEX_WRAP) == 209
    assert len(set(INDEX_WRAP)) == 209
    assert len(MAIN_KEYPOINTS_INDEX) == 141
    assert max(INDEX_WRAP) < LANDMARK_COUNT
    assert max(MAIN_KEYPOINTS_INDEX) < LANDMARK_COUNT


def test_subset_offsets_match_upstream_renumbering():
    # Upstream renumbers each group to its position inside the subset:
    # eyebrows (20) + nose (16) + inner lips (20) come before the outer lips.
    assert SUBSET_LIPS_OUTER[0] == 56
    assert len(SUBSET_LIPS_OUTER) == 20
    # ... + outer lips (20) + eyes (32) before the oval.
    assert SUBSET_FACE_OVAL[0] == 108
    assert len(SUBSET_FACE_OVAL) == 21


def test_smooth_array_is_zero_phase_and_keeps_edges():
    ramp = np.arange(10, dtype=float)[:, None]
    out = smooth_array(ramp, [0.25, 0.5, 0.25])
    # A linear ramp is invariant under a symmetric kernel.
    np.testing.assert_allclose(out[1:-1], ramp[1:-1])
    assert out[0, 0] == 0 and out[-1, 0] == 9


def test_smooth_array_rejects_even_kernels():
    with pytest.raises(ValueError):
        smooth_array(np.zeros((5, 1)), [0.5, 0.5])


def test_crop_mouth_is_clamped_to_the_frame():
    pts = np.zeros((len(MAIN_KEYPOINTS_INDEX), 3))
    pts[SUBSET_LIPS_OUTER, :2] = [50, 90]
    pts[SUBSET_FACE_OVAL, 0] = np.linspace(0, 100, len(SUBSET_FACE_OVAL))
    pts[SUBSET_FACE_OVAL, 1] = np.linspace(20, 120, len(SUBSET_FACE_OVAL))
    rect = crop_mouth(pts, img_w=120, img_h=100)
    x0, y0, x1, y1 = rect
    assert 0 <= x0 < x1 <= 120
    assert 0 <= y0 < y1 <= 100


def test_standardize_points_maps_crop_to_square():
    pts = np.array([[10.0, 20.0, -5.0], [110.0, 120.0, -3.0]])
    out = standardize_points(pts, np.array([10, 20, 110, 120]), STANDARD_SIZE)
    np.testing.assert_allclose(out[0, :2], [0, 0])
    np.testing.assert_allclose(out[1, :2], [STANDARD_SIZE, STANDARD_SIZE])
    # Depth is shifted so the nearest point is at zero.
    assert out[:, 2].max() == 0

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


@pytest.mark.parametrize("shape", [(11,), (11, 2), (11, 2, 3)])
def test_smoothing_handles_frame_axis_without_mutating_input(shape):
    source = np.arange(np.prod(shape), dtype=float).reshape(shape)
    source[5] += 7
    before = source.copy()
    actual = smooth_array(source, [0.25, 0.5, 0.25])
    expected = before.copy()
    expected[1:-1] = (
        before[:-2] * 0.25 + before[1:-1] * 0.5 + before[2:] * 0.25
    )
    np.testing.assert_allclose(actual, expected)
    np.testing.assert_array_equal(source, before)
    assert not np.shares_memory(actual, source)


@pytest.mark.parametrize("kernel", [[], [1, np.nan, 1], [[1]], [1, 1]])
def test_smoothing_rejects_invalid_kernels(kernel):
    with pytest.raises(ValueError):
        smooth_array(np.zeros((7, 2)), kernel)


def test_smoothing_short_empty_and_single_weight_sequences():
    source = np.array([[1, 4], [3, 8]])
    np.testing.assert_array_equal(smooth_array(source, [1, 2, 1]), source)
    np.testing.assert_array_equal(smooth_array(source, [2]), source * 2)
    assert smooth_array(np.empty((0, 2)), [1]).shape == (0, 2)


@pytest.mark.parametrize("crop", [[1, 1, 1, 2], [1, 1, 2, 0], [0, 0, np.inf, 2]])
def test_standardization_rejects_degenerate_or_nonfinite_crop(crop):
    with pytest.raises(ValueError):
        standardize_points(np.zeros((3, 3)), np.array(crop))


def test_standardization_preserves_isotropic_depth_and_nonsquare_contract():
    points = np.array([[10, 20, -10], [110, 70, 20]], dtype=float)
    before = points.copy()
    actual = standardize_points(points, np.array([10, 20, 110, 70]))
    np.testing.assert_allclose(actual, [[0, 0, -54], [180, 90, 0]])
    np.testing.assert_array_equal(points, before)


@pytest.mark.parametrize("points", [np.empty((0, 3)), np.zeros((3, 2)), [[0, 0, np.nan]]])
def test_standardization_rejects_invalid_points(points):
    with pytest.raises(ValueError):
        standardize_points(points, np.array([0, 0, 100, 100]))


def test_crop_preserves_calibrated_lip_offset_and_integer_truncation():
    points = np.zeros((len(MAIN_KEYPOINTS_INDEX), 3))
    points[SUBSET_FACE_OVAL, :2] = np.linspace(
        [100, 100], [300, 400], len(SUBSET_FACE_OVAL),
    )
    points[SUBSET_LIPS_OUTER, :2] = [190.3, 280.7]
    np.testing.assert_array_equal(crop_mouth(points, 720, 1280), [79, 182, 300, 403])


@pytest.mark.parametrize("width,height", [(0, 100), (100, -1), (100.5, 100), (True, 100)])
def test_crop_rejects_invalid_frame_dimensions(width, height):
    with pytest.raises(ValueError):
        crop_mouth(np.zeros((len(MAIN_KEYPOINTS_INDEX), 3)), width, height)


def test_crop_rejects_an_empty_or_external_face_extent():
    points = np.full((len(MAIN_KEYPOINTS_INDEX), 3), 500.0)
    with pytest.raises(ValueError):
        crop_mouth(points, 100, 100)

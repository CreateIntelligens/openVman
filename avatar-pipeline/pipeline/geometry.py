"""Validated NumPy operations for the avatar bundle's coordinate contract.

This module replaces the previous DH_live-ported implementation. Landmark
ordering and appearance calibration remain historical compatibility data in
``profiles/legacy_dh_live.json`` (DH_live, MIT); retaining that contract does
not establish legal clean-room independence.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


with Path(__file__).with_name("profiles").joinpath(
    "legacy_dh_live.json",
).open(encoding="utf-8") as _handle:
    COMPATIBILITY_PROFILE = json.load(_handle)

if COMPATIBILITY_PROFILE.get("schema_version") != 1:
    raise ValueError("unsupported avatar compatibility profile")

LANDMARK_COUNT = COMPATIBILITY_PROFILE["landmark_count"]
STANDARD_SIZE = COMPATIBILITY_PROFILE["standard_size"]
_TABLES = COMPATIBILITY_PROFILE["indices"]
for _name, _indices in _TABLES.items():
    if not _indices or any(
        type(index) is not int or not 0 <= index < LANDMARK_COUNT
        for index in _indices
    ) or len(set(_indices)) != len(_indices):
        raise ValueError(f"invalid landmark index table: {_name}")

INDEX_LEFT_EYEBROW = list(_TABLES["INDEX_LEFT_EYEBROW"])
INDEX_RIGHT_EYEBROW = list(_TABLES["INDEX_RIGHT_EYEBROW"])
INDEX_EYEBROW = INDEX_LEFT_EYEBROW + INDEX_RIGHT_EYEBROW
INDEX_NOSE_EDGE = list(_TABLES["INDEX_NOSE_EDGE"])
INDEX_NOSE_MID = list(_TABLES["INDEX_NOSE_MID"])
INDEX_NOSE = INDEX_NOSE_EDGE + INDEX_NOSE_MID
INDEX_LIPS_INNER = list(_TABLES["INDEX_LIPS_INNER"])
INDEX_LIPS_OUTER = list(_TABLES["INDEX_LIPS_OUTER"])
INDEX_LIPS = INDEX_LIPS_INNER + INDEX_LIPS_OUTER
INDEX_LEFT_EYE = list(_TABLES["INDEX_LEFT_EYE"])
INDEX_RIGHT_EYE = list(_TABLES["INDEX_RIGHT_EYE"])
INDEX_EYE = INDEX_LEFT_EYE + INDEX_RIGHT_EYE
INDEX_FACE_OVAL = list(_TABLES["INDEX_FACE_OVAL"])
INDEX_MUSCLE = list(_TABLES["INDEX_MUSCLE"])
INDEX_WRAP = list(_TABLES["INDEX_WRAP"])
WRAP_COUNT = len(INDEX_WRAP)

_GROUPS = (
    INDEX_EYEBROW,
    INDEX_NOSE,
    INDEX_LIPS_INNER,
    INDEX_LIPS_OUTER,
    INDEX_EYE,
    INDEX_FACE_OVAL,
    INDEX_MUSCLE,
)
MAIN_KEYPOINTS_INDEX = [index for group in _GROUPS for index in group]
_OFFSETS = np.cumsum([0] + [len(group) for group in _GROUPS])
SUBSET_LIPS_OUTER = list(range(int(_OFFSETS[3]), int(_OFFSETS[4])))
SUBSET_FACE_OVAL = list(range(int(_OFFSETS[5]), int(_OFFSETS[6])))


def _finite_array(value, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values")
    return array


def _positive_dimension(value, name: str) -> None:
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (int, float, np.integer, np.floating),
    ):
        raise ValueError(f"{name} must be a positive integer")
    if not np.isfinite(value) or value <= 0 or int(value) != value:
        raise ValueError(f"{name} must be a positive integer")


def crop_mouth(points: np.ndarray, img_w: int, img_h: int) -> np.ndarray:
    """Return an integer, frame-clipped lip ROI using the retained calibration.

    Input rows follow ``MAIN_KEYPOINTS_INDEX``. The face extent determines
    scale, and the lip centroid determines translation. Empty intersections
    are rejected rather than producing inverted crop coordinates.
    """
    _positive_dimension(img_w, "img_w")
    _positive_dimension(img_h, "img_h")
    values = _finite_array(points, "points")
    if values.ndim != 2 or values.shape[0] != len(MAIN_KEYPOINTS_INDEX):
        raise ValueError("points must follow MAIN_KEYPOINTS_INDEX")
    if values.shape[1] not in (2, 3):
        raise ValueError("points must have two or three coordinates per row")

    calibration = COMPATIBILITY_PROFILE["mouth_crop"]
    trim = calibration["oval_trim"]
    boundary = values[SUBSET_FACE_OVAL[trim:-trim], :2]
    frame_size = np.array([img_w, img_h])
    visible_min = np.maximum(boundary.min(axis=0), 0)
    visible_max = np.minimum(boundary.max(axis=0), frame_size)
    extent = visible_max - visible_min
    if np.any(extent <= 0):
        raise ValueError("face oval has no positive area inside the frame")

    radius = extent.max() * calibration["half_extent"]
    centre = values[SUBSET_LIPS_OUTER, :2].mean(axis=0)
    # Keep the historical slightly lower lip window for existing characters.
    offsets = np.array([
        [-1, -(1 - calibration["vertical_bias"])],
        [1, 1 + calibration["vertical_bias"]],
    ])
    corners = np.trunc(centre + offsets * radius)
    corners = np.clip(corners, 0, frame_size)
    if np.any(corners[1] <= corners[0]):
        raise ValueError("mouth crop has no positive area inside the frame")
    return corners.astype(np.int64).reshape(4)


def smooth_array(array: np.ndarray, weight: list[float]) -> np.ndarray:
    """Filter axis zero, preserving the source frames outside complete windows.

    Any finite odd-length kernel is accepted without implicit normalization.
    Symmetric weights give a zero-phase filter. Trailing dimensions may be
    scalar samples, coordinates or complete matrices.
    """
    samples = _finite_array(array, "array")
    kernel = _finite_array(weight, "weight")
    if samples.ndim == 0:
        raise ValueError("array must have a frame axis")
    if kernel.ndim != 1 or kernel.size == 0 or kernel.size % 2 != 1:
        raise ValueError("smoothing kernel must have a nonempty odd length")
    result = samples.copy()
    if len(samples) < len(kernel):
        return result
    windows = np.lib.stride_tricks.sliding_window_view(
        samples, len(kernel), axis=0,
    )
    # NumPy appends the window axis; contracting it keeps all other axes.
    filtered = np.einsum("...k,k->...", windows, kernel, optimize=False)
    start = len(kernel) // 2
    result[start:start + len(filtered)] = filtered
    return result


def standardize_points(
    points: np.ndarray, crop: np.ndarray, size: int = STANDARD_SIZE,
) -> np.ndarray:
    """Apply crop-origin translation and isotropic scaling to xyz coordinates.

    Depth uses the same scale as x and y and is translated by its maximum.
    The crop width remains the scale reference even for nonsquare input ROIs,
    as required by the bundle's existing 180-unit coordinate contract.
    """
    _positive_dimension(size, "size")
    values = _finite_array(points, "points")
    bounds = _finite_array(crop, "crop")
    if values.ndim != 2 or values.shape[1] != 3 or not len(values):
        raise ValueError("points must be a nonempty array of xyz triples")
    if bounds.shape != (4,) or np.any(bounds[2:] <= bounds[:2]):
        raise ValueError("crop must contain increasing x/y bounds")
    origin = np.array([bounds[0], bounds[1], values[:, 2].max()])
    translated = values - origin
    return translated * size / (bounds[2] - bounds[0])

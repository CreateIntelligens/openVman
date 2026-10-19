"""Landmark index tables and the pure-numpy geometry the bundle builder needs.

The index tables and the three helpers (``crop_mouth``, ``smooth_array``,
``standardize_points``) are ported from DH_live (MIT licence,
https://github.com/kleinlee/DH_live) with the torch code path dropped: the
pipeline only ever smooths offline arrays, and numpy is enough for that.
"""

from __future__ import annotations

import numpy as np

INDEX_LEFT_EYEBROW = [276, 283, 282, 295, 285, 336, 296, 334, 293, 300]
INDEX_RIGHT_EYEBROW = [46, 53, 52, 65, 55, 107, 66, 105, 63, 70]
INDEX_EYEBROW = INDEX_LEFT_EYEBROW + INDEX_RIGHT_EYEBROW

INDEX_NOSE_EDGE = [343, 355, 358, 327, 326, 2, 97, 98, 129, 126, 114]
INDEX_NOSE_MID = [6, 197, 195, 5, 4]
INDEX_NOSE = INDEX_NOSE_EDGE + INDEX_NOSE_MID

INDEX_LIPS_INNER = [
    78, 95, 88, 178, 87, 14, 317, 402, 318, 324,
    308, 415, 310, 311, 312, 13, 82, 81, 80, 191,
]
INDEX_LIPS_OUTER = [
    61, 146, 91, 181, 84, 17, 314, 405, 321, 375,
    291, 409, 270, 269, 267, 0, 37, 39, 40, 185,
]
INDEX_LIPS = INDEX_LIPS_INNER + INDEX_LIPS_OUTER

INDEX_LEFT_EYE = [
    263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466,
]
INDEX_RIGHT_EYE = [
    33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246,
]
INDEX_EYE = INDEX_LEFT_EYE + INDEX_RIGHT_EYE

INDEX_FACE_OVAL = [
    454, 323, 361, 288, 397, 365,
    379, 378, 400, 377, 152, 148, 176, 149, 150,
    136, 172, 58, 132, 93, 234,
]

INDEX_MUSCLE = [371, 266, 425, 427, 434, 394, 169, 214, 207, 205, 36, 142]

#: The subset of MediaPipe's 478 landmarks that drives mouth cropping.
MAIN_KEYPOINTS_INDEX = (
    INDEX_EYEBROW + INDEX_NOSE + INDEX_LIPS + INDEX_EYE + INDEX_FACE_OVAL + INDEX_MUSCLE
)

#: ``crop_mouth`` receives the MAIN_KEYPOINTS_INDEX subset, so it addresses
#: lips and oval by their position inside that subset, not by raw landmark id.
_LIPS_OUTER_OFFSET = len(INDEX_EYEBROW) + len(INDEX_NOSE) + len(INDEX_LIPS_INNER)
SUBSET_LIPS_OUTER = list(range(_LIPS_OUTER_OFFSET, _LIPS_OUTER_OFFSET + len(INDEX_LIPS_OUTER)))
_OVAL_OFFSET = len(INDEX_EYEBROW) + len(INDEX_NOSE) + len(INDEX_LIPS) + len(INDEX_EYE)
SUBSET_FACE_OVAL = list(range(_OVAL_OFFSET, _OVAL_OFFSET + len(INDEX_FACE_OVAL)))

#: The 209 landmarks the renderer warps; ``json_data`` carries them in this order.
INDEX_WRAP = [
    0, 2, 11, 12, 13, 14, 15, 16, 17, 18, 32, 36, 37, 38, 39, 40, 41, 42, 43, 50, 57, 58, 61,
    62, 72, 73, 74, 76, 77, 78, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 95,
    96, 97, 98, 100, 101, 106, 116, 117, 118, 119, 123, 129, 132, 135, 136, 137, 138, 140,
    142, 146, 147, 148, 149, 150, 152, 164, 165, 167, 169, 170, 171, 172, 175, 176, 177,
    178, 179, 180, 181, 182, 183, 184, 185, 186, 187, 191, 192, 194, 199, 200, 201, 202,
    203, 204, 205, 206, 207, 208, 210, 211, 212, 213, 214, 215, 216, 227, 234, 262, 266,
    267, 268, 269, 270, 271, 272, 273, 280, 287, 288, 291, 292, 302, 303, 304, 306, 307,
    308, 310, 311, 312, 313, 314, 315, 316, 317, 318, 319, 320, 321, 322, 323, 324, 325,
    326, 327, 329, 330, 335, 345, 346, 347, 348, 352, 358, 361, 364, 365, 366, 367, 369,
    371, 375, 376, 377, 378, 379, 391, 393, 394, 395, 396, 397, 400, 401, 402, 403, 404,
    405, 406, 407, 408, 409, 410, 411, 415, 416, 418, 421, 422, 423, 424, 425, 426, 427,
    428, 430, 431, 432, 433, 434, 435, 436, 447, 454,
]

LANDMARK_COUNT = 478
WRAP_COUNT = len(INDEX_WRAP)
#: Side of the square the renderer works in; landmarks and the pose matrix
#: are expressed in this space.
STANDARD_SIZE = 180


def crop_mouth(points: np.ndarray, img_w: int, img_h: int) -> np.ndarray:
    """Square-ish crop around the lips, sized from the face oval.

    ``points`` are the ``MAIN_KEYPOINTS_INDEX`` landmarks of one frame.
    """
    center_x = np.mean(points[SUBSET_LIPS_OUTER, 0])
    center_y = np.mean(points[SUBSET_LIPS_OUTER, 1])
    oval = points[SUBSET_FACE_OVAL[2:-2]]
    x_min = max(0, np.min(oval[:, 0]))
    y_min = max(0, np.min(oval[:, 1]))
    x_max = min(np.max(oval[:, 0]), img_w)
    y_max = min(np.max(oval[:, 1]), img_h)
    new_size = max(x_max - x_min, y_max - y_min) * 0.46

    x_min = int(center_x - new_size)
    y_min = int(center_y - new_size * 0.89)
    x_max = int(center_x + new_size)
    y_max = int(center_y + new_size * 1.11)
    return np.array([
        max(0, x_min), max(0, y_min), min(img_w, x_max), min(img_h, y_max),
    ])


def smooth_array(array: np.ndarray, weight: list[float]) -> np.ndarray:
    """Zero-phase 1-D smoothing along axis 0 with an odd, centred kernel.

    Frames within ``len(weight) // 2`` of either end are copied through
    unchanged, exactly like the upstream implementation, so the first and
    last frames stay anchored to the source.
    """
    if len(weight) % 2 != 1:
        raise ValueError("smoothing kernel must have an odd length")
    pad = len(weight) // 2
    kernel = np.array(weight, dtype=np.float64)[:, np.newaxis]
    out = np.array(array, dtype=np.float64, copy=True)
    for i in range(pad, len(array) - pad):
        out[i] = np.sum(array[i - pad:i + pad + 1] * kernel, axis=0)
    return out


def standardize_points(
    points: np.ndarray, crop: np.ndarray, size: int = STANDARD_SIZE,
) -> np.ndarray:
    """Map 3-D landmarks into the ``size``-square defined by ``crop``.

    Depth is shifted so the nearest point sits at zero and scaled with the
    crop width, matching what the renderer expects from ``json_data``.
    """
    x_min, y_min, x_max, _ = crop
    pts = np.array(points, dtype=np.float64, copy=True)
    pts[:, 2] -= np.max(pts[:, 2])
    return (pts - np.array([x_min, y_min, 0])) * size / (x_max - x_min)

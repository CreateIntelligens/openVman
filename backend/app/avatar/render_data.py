"""Bounded conversion of stored avatar bundles to the CPU render contract.

The legacy encrypted template and crop data remain compatibility inputs.
Conversion only adds a sidecar; it never rewrites a character's source assets.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import io
import json
import math
import os
import subprocess
import tempfile
import zlib
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

RENDER_FILENAME = "render_data.json.gz"
RENDER_SCHEMA = "openvman.render.v1"
TEMPLATE_VALUES = 465 * 3
LEGACY_ROW_VALUES = 16 + 209 * 2
RENDER_ROW_VALUES = LEGACY_ROW_VALUES + 4 + (465 - 209) * 2
MAX_FRAMES = 100_000
MAX_FRAME_SIDE = 8192
ERROR_MESSAGE = "角色渲染資料無效或無法轉換，請重新產製素材包"


class RenderDataError(ValueError):
    """A render payload cannot be accepted or derived safely."""


def _reject_constant(_value: str) -> None:
    raise RenderDataError(ERROR_MESSAGE)


def _json(payload: bytes) -> Any:
    try:
        return json.loads(payload, parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise RenderDataError(ERROR_MESSAGE) from exc


def _decompress(data: bytes, limit: int) -> bytes:
    if len(data) > limit:
        raise RenderDataError(ERROR_MESSAGE)
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            payload = stream.read(limit + 1)
    except (EOFError, OSError, zlib.error) as exc:
        raise RenderDataError(ERROR_MESSAGE) from exc
    if len(payload) > limit:
        raise RenderDataError(ERROR_MESSAGE)
    return payload


def _numbers(value: Any, count: int) -> list:
    if not isinstance(value, list) or len(value) != count:
        raise RenderDataError(ERROR_MESSAGE)
    for number in value:
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise RenderDataError(ERROR_MESSAGE)
        try:
            finite = math.isfinite(number)
        except OverflowError:
            finite = False
        if not finite:
            raise RenderDataError(ERROR_MESSAGE)
    return value


def _size(value: Any) -> list[int]:
    if not isinstance(value, list) or len(value) != 2:
        raise RenderDataError(ERROR_MESSAGE)
    if any(type(side) is not int or not 0 < side <= MAX_FRAME_SIDE for side in value):
        raise RenderDataError(ERROR_MESSAGE)
    return value


def validate_render_data(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise RenderDataError(ERROR_MESSAGE)
    if payload.get("schema") == "openvman.render.v2":
        return _validate_video_geometry(payload)
    if payload.get("schema") != RENDER_SCHEMA:
        raise RenderDataError(ERROR_MESSAGE)
    if type(payload.get("frameRate")) is not int or payload["frameRate"] != 25:
        raise RenderDataError(ERROR_MESSAGE)
    if payload.get("denseReference") != "affine-rest":
        raise RenderDataError(ERROR_MESSAGE)
    _size(payload.get("frameSize"))
    _numbers(payload.get("template"), TEMPLATE_VALUES)
    frames = payload.get("frames")
    if not isinstance(frames, list) or not 0 < len(frames) <= MAX_FRAMES:
        raise RenderDataError(ERROR_MESSAGE)
    for row in frames:
        _numbers(row, RENDER_ROW_VALUES)
        rect = row[LEGACY_ROW_VALUES:LEGACY_ROW_VALUES + 4]
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            raise RenderDataError(ERROR_MESSAGE)
    # Store exactly the public contract, without arbitrary caller-owned fields.
    return {name: payload[name] for name in (
        "schema", "frameRate", "frameSize", "template", "frames", "denseReference",
    )}


def _validate_video_geometry(payload: dict) -> dict:
    """Accept independently tracked lips without restoring a legacy template."""
    if (
        type(payload.get("frameRate")) is not int
        or payload["frameRate"] != 25
        or payload.get("geometrySource") != "mediapipe-video"
    ):
        raise RenderDataError(ERROR_MESSAGE)
    width, height = _size(payload.get("frameSize"))
    frames = payload.get("frames")
    if not isinstance(frames, list) or not 0 < len(frames) <= MAX_FRAMES:
        raise RenderDataError(ERROR_MESSAGE)
    clean_frames = []
    for frame in frames:
        if not isinstance(frame, dict):
            raise RenderDataError(ERROR_MESSAGE)
        left, top, right, bottom = _numbers(frame.get("region"), 4)
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise RenderDataError(ERROR_MESSAGE)
        for name in ("outer", "inner"):
            points = _numbers(frame.get(name), 40)
            if any(not 0 <= point <= 180 for point in points):
                raise RenderDataError(ERROR_MESSAGE)
            width_squared = (
                (points[20] - points[0]) ** 2
                + (points[21] - points[1]) ** 2
            )
            if not 1 <= width_squared <= 180 ** 2:
                raise RenderDataError(ERROR_MESSAGE)
        _validate_outer_rays(frame["outer"])
        clean = {name: frame[name] for name in ("region", "outer", "inner")}
        # Optional face scale: the distance between the outer eye corners, in the
        # same local units. Older sidecars lack it and remain valid.
        if "eyeSpan" in frame:
            (eye_span,) = _numbers([frame["eyeSpan"]], 1)
            if not 1 <= eye_span <= 4 * 180:
                raise RenderDataError(ERROR_MESSAGE)
            clean["eyeSpan"] = eye_span
        clean_frames.append(clean)
    result = {
        "schema": "openvman.render.v2",
        "frameRate": 25,
        "frameSize": [width, height],
        "geometrySource": "mediapipe-video",
        "frames": clean_frames,
    }
    # Provenance is metadata, never a claim established by accepting an upload.
    source = payload.get("provenance")
    if isinstance(source, dict):
        result["provenance"] = {
            name: value for name, value in source.items()
            if name in (
                "videoSha256", "generator", "implementationSha256",
                "coordinateSpace", "mediapipeVersion",
            )
            and isinstance(value, str) and len(value) <= 256
        }
        detector = source.get("detector")
        if isinstance(detector, dict):
            models = detector.get("models", {})
            result["provenance"]["detector"] = {
                name: value for name, value in detector.items()
                if name in ("package", "version")
                and isinstance(value, str) and len(value) <= 64
            }
            if isinstance(models, dict):
                result["provenance"]["detector"]["models"] = {
                    name: value for name, value in models.items()
                    if name in (
                        "modules/face_detection/face_detection_short_range.tflite",
                        "modules/face_detection/face_detection_full_range_sparse.tflite",
                        "modules/face_landmark/face_landmark.tflite",
                    )
                    and isinstance(value, str) and len(value) == 64
                    and all(char in "0123456789abcdef" for char in value)
                }
    return result


def _validate_outer_rays(ring: list) -> None:
    """Keep every interpolated support ray away from its undefined origin.

    The client uses these same Catmull-Rom samples to reach the ROI boundary.
    Checking just the measured points misses a curve crossing the mouth centre.
    """
    centre = [(ring[axis] + ring[20 + axis]) / 2 for axis in range(2)]
    for sample in range(80):
        index, quarter = divmod(sample, 4)
        t = quarter / 4
        point = []
        for axis in range(2):
            p0, p1, p2, p3 = (
                ring[((index + offset) % 20) * 2 + axis]
                for offset in (-1, 0, 1, 2)
            )
            point.append(0.5 * (
                2 * p1 + (-p0 + p2) * t
                + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3
            ))
        if sum((point[axis] - centre[axis]) ** 2 for axis in range(2)) < 1e-12:
            raise RenderDataError(ERROR_MESSAGE)


def _encode(payload: dict, limit: int) -> bytes:
    try:
        raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    except (OverflowError, ValueError) as exc:
        raise RenderDataError(ERROR_MESSAGE) from exc
    if len(raw) > limit:
        raise RenderDataError(ERROR_MESSAGE)
    compressed = gzip.compress(raw, mtime=0)
    if len(compressed) > limit:
        raise RenderDataError(ERROR_MESSAGE)
    return compressed


def extract_uploaded_render_data(data: bytes, *, limit: int) -> bytes | None:
    """Validate an uploaded JSON package and extract an optional modern sidecar."""
    outer = _json(_decompress(data, limit))
    if not isinstance(outer, dict) or "render_data" not in outer:
        return None
    return _encode(validate_render_data(outer["render_data"]), limit)


def _read(path: Path, limit: int) -> bytes:
    try:
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError as exc:
        raise RenderDataError(ERROR_MESSAGE) from exc
    if len(data) > limit:
        raise RenderDataError(ERROR_MESSAGE)
    return data


def _video_size(video: Path) -> list[int]:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "json", str(video),
            ],
            capture_output=True, check=True, timeout=15,
        )
        streams = _json(result.stdout)["streams"]
        return _size([streams[0]["width"], streams[0]["height"]])
    except (
        IndexError,
        KeyError,
        OSError,
        subprocess.SubprocessError,
        TypeError,
    ) as exc:
        raise RenderDataError(ERROR_MESSAGE) from exc


def _decrypt_inner(combined: Any, key: str | None, limit: int) -> dict:
    try:
        encoded_key = (key or "").encode("ascii")
        if len(encoded_key) != 16 or not isinstance(combined, str):
            raise RenderDataError(ERROR_MESSAGE)
        ciphertext = base64.b64decode(combined, validate=True)
        if not 32 <= len(ciphertext) <= limit or len(ciphertext) % 16:
            raise RenderDataError(ERROR_MESSAGE)
        decryptor = Cipher(
            algorithms.AES(encoded_key), modes.CBC(ciphertext[:16]),
        ).decryptor()
        padded = decryptor.update(ciphertext[16:]) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        raw = unpadder.update(padded) + unpadder.finalize()
        inner = _json(raw)
    except (binascii.Error, UnicodeError, ValueError) as exc:
        raise RenderDataError(ERROR_MESSAGE) from exc
    if not isinstance(inner, dict):
        raise RenderDataError(ERROR_MESSAGE)
    return inner


def build_legacy_render_data(
    data_path: Path, video_path: Path, *, key: str | None, limit: int,
) -> bytes:
    outer = _json(_decompress(_read(data_path, limit), limit))
    if not isinstance(outer, dict):
        raise RenderDataError(ERROR_MESSAGE)
    if "render_data" in outer:
        return _encode(validate_render_data(outer["render_data"]), limit)
    inner = _decrypt_inner(outer.get("combined_data"), key, limit)
    template = _numbers(inner.get("face3D_obj"), TEMPLATE_VALUES)
    rows = outer.get("json_data")
    rects = inner.get("rect")
    if (
        not isinstance(rows, list) or not 0 < len(rows) <= MAX_FRAMES
        or not isinstance(rects, list) or len(rects) != len(rows)
        or type(inner.get("frame_num")) is not int
        or inner["frame_num"] != len(rows)
    ):
        raise RenderDataError(ERROR_MESSAGE)
    frames = []
    for row, rect in zip(rows, rects, strict=True):
        _numbers(row, LEGACY_ROW_VALUES)
        _numbers(rect, 4)
        dense = []
        # Matrices serialize row-major and points multiply as row vectors.
        for start in range(209 * 3, TEMPLATE_VALUES, 3):
            point = template[start:start + 3] + [1]
            dense.extend(
                sum(point[axis] * row[axis * 4 + column] for axis in range(4))
                for column in range(2)
            )
        frames.append(row + rect + dense)
    payload = validate_render_data({
        "schema": RENDER_SCHEMA,
        "frameRate": 25,
        "frameSize": _video_size(video_path),
        "template": template,
        "frames": frames,
        "denseReference": "affine-rest",
    })
    return _encode(payload, limit)


def write_render_sidecar(character_dir: Path, data: bytes) -> Path:
    """Atomically replace only the fixed sidecar within a resolved directory."""
    target = character_dir / RENDER_FILENAME
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=character_dir, prefix=".render-data-", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
        os.replace(temporary, target)
    except OSError as exc:
        raise RenderDataError(ERROR_MESSAGE) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target

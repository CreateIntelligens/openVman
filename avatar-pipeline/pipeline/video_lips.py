"""Build renderer geometry directly from a supplied video and MediaPipe.

The renderer receives measured lip contours rather than a shared face template,
extracted mesh, blendshape texture or encrypted avatar bundle. MediaPipe is a
third-party detector; its model identities are retained in the provenance.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path

import numpy as np

FRAME_RATE = 25
LOCAL_SIZE = 180
OUTER_LIP = (
    61, 185, 40, 39, 37, 0, 267, 269, 270, 409,
    291, 375, 321, 405, 314, 17, 84, 181, 91, 146,
)
INNER_LIP = (
    78, 191, 80, 81, 82, 13, 312, 311, 310, 415,
    308, 324, 318, 402, 317, 14, 87, 178, 88, 95,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def contours_from_landmarks(points, width: int, height: int):
    """Map measured pixel coordinates to a square local mouth region.

    A lip-width-scaled region keeps the boundary well outside the moving lips.
    Clipping translates the square rather than distorting its aspect ratio.
    No shared canonical coordinates or pose-fitting data enter this operation.
    """
    if (
        type(width) is not int or type(height) is not int
        or not (0 < width <= 8192 and 0 < height <= 8192)
    ):
        raise ValueError("Invalid video dimensions")
    values = np.asarray(points, dtype=np.float64)
    if (
        values.ndim != 2 or values.shape[0] < 416
        or values.shape[1] != 2 or not np.isfinite(values).all()
    ):
        raise ValueError("Expected finite measured face xy coordinates")
    outer = values[list(OUTER_LIP)]
    inner = values[list(INNER_LIP)]
    mouth_width = np.linalg.norm(outer[10] - outer[0])
    if mouth_width < 2:
        raise ValueError("Degenerate measured mouth")
    side = min(max(mouth_width * 2.4, 32), width, height)
    centre = (outer[0] + outer[10]) / 2
    top_left = np.clip(centre - side / 2, 0, [width - side, height - side])
    bottom_right = top_left + side
    if np.any(outer < top_left) or np.any(outer > bottom_right):
        raise ValueError("Mouth extends beyond its video crop")
    scale = LOCAL_SIZE / side
    return {
        "region": [*top_left.tolist(), *bottom_right.tolist()],
        "outer": ((outer - top_left) * scale).reshape(-1).tolist(),
        "inner": ((inner - top_left) * scale).reshape(-1).tolist(),
    }


def _video_stream(video: Path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries",
            "stream=width,height,codec_name:stream_tags=alpha_mode",
            "-of", "json", str(video),
        ],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)["streams"][0]


def _video_dimensions(video: Path):
    stream = _video_stream(video)
    width, height = stream["width"], stream["height"]
    if not (0 < width <= 8192 and 0 < height <= 8192):
        raise ValueError("Unsupported video dimensions")
    return width, height


def _rgb_frames(video: Path, width: int, height: int):
    stream = _video_stream(video)
    codec = stream.get("codec_name")
    has_alpha = str(stream.get("tags", {}).get("alpha_mode", "")) == "1"
    # Native VP8/VP9 decoding silently drops WebM's separate alpha plane.
    # Detection receives a neutral background; the source video is untouched.
    decoder = {"vp8": "libvpx", "vp9": "libvpx-vp9"}.get(codec)
    decode_options = ["-c:v", decoder] if has_alpha and decoder else []
    channels = 4 if has_alpha else 3
    command = [
        "ffmpeg", "-v", "error", "-threads", "2", *decode_options,
        "-i", str(video),
        "-an", "-vf", f"fps={FRAME_RATE}", "-f", "rawvideo",
        "-pix_fmt", "rgba" if has_alpha else "rgb24",
        "-threads", "2", "pipe:1",
    ]
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        try:
            frame_bytes = width * height * channels
            while True:
                data = process.stdout.read(frame_bytes)
                if not data:
                    break
                if len(data) != frame_bytes:
                    raise ValueError("Truncated decoded video frame")
                pixels = np.frombuffer(data, np.uint8).reshape(
                    height, width, channels,
                )
                yield _flatten_rgba(pixels) if has_alpha else pixels
            if process.wait() != 0:
                errors.seek(0)
                raise ValueError(errors.read().decode(errors="replace")[-1000:])
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.terminate()
                process.wait()


def _flatten_rgba(pixels):
    values = pixels.astype(np.uint16)
    alpha = values[..., 3:4]
    return ((
        values[..., :3] * alpha + 128 * (255 - alpha) + 127
    ) // 255).astype(np.uint8)


def _detector_provenance(mp):
    root = Path(mp.__file__).parent
    models = {}
    for relative in (
        "modules/face_detection/face_detection_short_range.tflite",
        "modules/face_detection/face_detection_full_range_sparse.tflite",
        "modules/face_landmark/face_landmark.tflite",
    ):
        model = root / relative
        if not model.is_file():
            raise ValueError(f"Detector model identity missing: {relative}")
        models[relative] = sha256_file(model)
    return {"package": "mediapipe", "version": mp.__version__, "models": models}


def _square_face_region(bounds, width: int, height: int):
    values = np.asarray(bounds, dtype=float)
    if (
        values.shape != (4,) or not np.isfinite(values).all()
        or values[2] <= values[0] or values[3] <= values[1]
    ):
        raise ValueError("Invalid detected face bounds")
    extent = values[2:] - values[:2]
    side = min(int(np.ceil(extent.max() * 1.5)), width, height)
    if side < 8:
        raise ValueError("Detected face is too small")
    centre = (values[:2] + values[2:]) / 2
    origin = np.rint(np.clip(
        centre - side / 2, 0, [width - side, height - side],
    )).astype(int)
    return (*origin.tolist(), *(origin + side).tolist())


def _long_range_region(detector, rgb, width: int, height: int):
    result = detector.process(rgb)
    faces = result.detections or []
    if len(faces) != 1:
        raise ValueError("Long-range localization requires exactly one face")
    face = faces[0]
    rect = face.location_data.relative_bounding_box
    bounds = np.array([
        rect.xmin * width,
        rect.ymin * height,
        (rect.xmin + rect.width) * width,
        (rect.ymin + rect.height) * height,
    ])
    return _square_face_region(bounds, width, height)


def _tracked_landmarks(mp, iterator, width, height, tracking):
    options = {
        "static_image_mode": False,
        "max_num_faces": 1,
        "refine_landmarks": False,
        "min_detection_confidence": 0.5,
        "min_tracking_confidence": 0.5,
    }
    # A separate local graph prevents the failed full-frame track state from
    # leaking into a new coordinate system. All graphs close on any failure.
    with ExitStack() as resources:
        full = resources.enter_context(
            mp.solutions.face_mesh.FaceMesh(**options),
        )
        local = long_range = region = None
        for index, rgb in enumerate(iterator):
            origin = np.zeros(2)
            scale = np.array([width, height])
            if region is None:
                result = full.process(rgb)
            else:
                left, top, right, bottom = region
                result = local.process(np.ascontiguousarray(rgb[top:bottom, left:right]))
                origin = np.array([left, top])
                scale = np.array([right - left, bottom - top])
            faces = result.multi_face_landmarks or []
            if len(faces) != 1:
                if long_range is None:
                    long_range = resources.enter_context(
                        mp.solutions.face_detection.FaceDetection(
                            model_selection=1, min_detection_confidence=0.5,
                        ),
                    )
                    local = resources.enter_context(
                        mp.solutions.face_mesh.FaceMesh(**options),
                    )
                region = _long_range_region(long_range, rgb, width, height)
                left, top, right, bottom = region
                result = local.process(np.ascontiguousarray(rgb[top:bottom, left:right]))
                faces = result.multi_face_landmarks or []
                origin = np.array([left, top])
                scale = np.array([right - left, bottom - top])
                tracking["relocations"] += 1
            if len(faces) != 1:
                raise ValueError(f"Frame {index}: exactly one face required")
            points = np.array([
                [point.x, point.y] for point in faces[0].landmark
            ]) * scale + origin
            if not np.isfinite(points).all():
                raise ValueError(f"Frame {index}: nonfinite measured face")
            if region is None:
                tracking["fullFrameFrames"] += 1
            else:
                tracking["roiFrames"] += 1
                # Follow the measured face rather than locking a frame-zero box.
                minimum = points.min(axis=0)
                maximum = points.max(axis=0)
                region = _square_face_region(
                    [*minimum, *maximum], width, height,
                )
            yield points


def generate_video_lips(video: Path, *, progress=None):
    """Track every 25 fps frame; a missing face fails the complete operation."""
    import mediapipe as mp

    video = Path(video)
    video_hash = sha256_file(video)
    width, height = _video_dimensions(video)
    frames = []
    tracking = {"fullFrameFrames": 0, "roiFrames": 0, "relocations": 0}
    iterator = _rgb_frames(video, width, height)
    try:
        measured = _tracked_landmarks(mp, iterator, width, height, tracking)
        try:
            for index, points in enumerate(measured):
                frames.append(contours_from_landmarks(points, width, height))
                if progress:
                    progress(index + 1)
        finally:
            measured.close()
    finally:
        close = getattr(iterator, "close", None)
        if close is not None:
            close()
    if not frames:
        raise ValueError("Video has no decodable frames")
    if sha256_file(video) != video_hash:
        raise ValueError("Video changed while tracking")
    return {
        "schema": "openvman.render.v2",
        "frameRate": FRAME_RATE,
        "frameSize": [width, height],
        "geometrySource": "mediapipe-video",
        "frames": frames,
        "provenance": {
            "videoSha256": video_hash,
            "generator": "openvman.video-lips.v1",
            "implementationSha256": sha256_file(Path(__file__)),
            "detector": _detector_provenance(mp),
            "tracking": tracking,
            "coordinateSpace": "local-180-xy",
            "inputs": ["input-video", "MediaPipe FaceMesh"],
        },
    }


def write_video_lips(output: Path, payload):
    """Publish deterministic compressed bytes only after complete encoding."""
    output = Path(output)
    data = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
    compressed = gzip.compress(data, mtime=0)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(compressed)
    try:
        temporary.chmod(0o644)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.video.resolve() == args.output.resolve():
        parser.error("Output must not overwrite the input video")
    payload = generate_video_lips(args.video)
    write_video_lips(args.output, payload)
    print(json.dumps({
        "schema": payload["schema"],
        "frames": len(payload["frames"]),
        "frameSize": payload["frameSize"],
        "provenance": payload["provenance"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()

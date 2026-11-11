"""Portable renderer data generated without an Avatar runtime or browser dump.

The preserved rig/template are compatibility data; dense rest anchors are now
calculated from the pose, rather than extracted from a hidden runtime heap.
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
from pathlib import Path

import numpy as np


def render_data(rows, rectangles, template, width, height):
    poses = np.asarray(rows, dtype=np.float64)
    crops = np.asarray(rectangles, dtype=np.float64)
    rest = np.asarray(template, dtype=np.float64)
    if (
        poses.ndim != 2
        or poses.shape[1] != 434
        or not len(poses)
        or crops.shape != (len(poses), 4)
        or rest.shape != (1395,)
        or not all(np.isfinite(a).all() for a in (poses, crops, rest))
    ):
        raise ValueError("Invalid renderer geometry")
    if (
        type(width) is not int
        or type(height) is not int
        or not (0 < width <= 8192 and 0 < height <= 8192)
    ):
        raise ValueError("Invalid renderer frame dimensions")
    if np.any(crops[:, 2:] <= crops[:, :2]):
        raise ValueError("Empty renderer crop")
    homogeneous = np.column_stack([rest.reshape(465, 3), np.ones(465)])
    matrices = poses[:, :16].reshape(-1, 4, 4)
    projected = np.einsum("ij,fjk->fik", homogeneous, matrices)
    frames = np.concatenate(
        [
            poses,
            crops,
            projected[:, 209:, :2].reshape(len(poses), -1),
        ],
        axis=1,
    )
    if not np.isfinite(frames).all():
        raise ValueError("Nonfinite projected reference geometry")
    return {
        "schema": "openvman.render.v1",
        "frameRate": 25,
        "frameSize": [int(width), int(height)],
        "template": rest.tolist(),
        "frames": frames.tolist(),
        "denseReference": "affine-rest",
    }


def write_render_data(path, rows, rectangles, template, width, height):
    payload = render_data(rows, rectangles, template, width, height)
    target = Path(path)
    temporary = target.with_suffix(".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as stream:
        json.dump(payload, stream, allow_nan=False, separators=(",", ":"))
    temporary.replace(target)
    return target


def main():
    from .bundle import decrypt_inner, load_bundle_key

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    key = load_bundle_key()
    converted = []
    failures = []
    for source in sorted(args.directory.rglob("combined_data.json.gz")):
        output = source.with_name("render_data.json.gz")
        if output.exists() and not args.overwrite:
            continue
        try:
            outer = json.loads(gzip.decompress(source.read_bytes()))
            inner = json.loads(decrypt_inner(key, outer["combined_data"]))
            metadata = json.loads(
                subprocess.check_output(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-show_entries",
                        "stream=width,height",
                        "-of",
                        "json",
                        str(source.with_name("01.webm")),
                    ],
                    text=True,
                )
            )["streams"][0]
            write_render_data(
                output,
                outer["json_data"],
                inner["rect"],
                inner["face3D_obj"],
                metadata["width"],
                metadata["height"],
            )
            converted.append(str(output))
        except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
            failures.append({"file": str(source), "error": str(error)})
    print(json.dumps({"converted": converted, "failures": failures}, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

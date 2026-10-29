"""Command-line entry: ``python -m pipeline.cli --input clip.mp4 --output dir``.

Progress goes to stdout as one JSON object per line so the worker can relay
it without parsing free text.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bundle import LOOP_MODES, build_bundle, load_bundle_key
from .frames import DEFAULT_MAX_SIDE, LOOP_SEAM_THRESHOLD, VideoProcessingError


def _emit(stage: str, done: int, total: int) -> None:
    print(json.dumps({"stage": stage, "done": done, "total": total}), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an avatar bundle from a silent video")
    parser.add_argument("--input", "-i", required=True, type=Path, help="source video (.mp4/.mov/.webm) or still image (.png/.jpg/.webp)")
    parser.add_argument("--output", "-o", required=True, type=Path, help="bundle directory")
    parser.add_argument(
        "--max-side", type=int, default=DEFAULT_MAX_SIDE,
        help=f"scale the longest side down to this many pixels (default {DEFAULT_MAX_SIDE})",
    )
    parser.add_argument(
        "--loop", choices=LOOP_MODES, default="auto",
        help="append the clip played backwards: auto = only when first and last frame differ",
    )
    parser.add_argument(
        "--seam-threshold", type=float, default=LOOP_SEAM_THRESHOLD,
        help=f"mean grey difference that counts as a jump (default {LOOP_SEAM_THRESHOLD})",
    )
    parser.add_argument(
        "--key", default=None,
        help="16-char bundle key; defaults to AVATAR_BUNDLE_KEY from the environment",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="suppress per-frame progress lines",
    )
    args = parser.parse_args(argv)

    try:
        key = load_bundle_key(args.key)
        result = build_bundle(
            args.input,
            args.output,
            key=key,
            max_side=args.max_side,
            loop_mode=args.loop,
            seam_threshold=args.seam_threshold,
            progress=None if args.quiet else _emit,
        )
    except (VideoProcessingError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(json.dumps({"stage": "failed", "error": str(exc)}), flush=True)
        return 1

    print(json.dumps({
        "stage": "done",
        "frame_count": result.frame_count,
        "width": result.width,
        "height": result.height,
        "alpha": result.has_alpha,
        "seam_difference": result.seam_difference,
        "ping_pong": result.ping_pong,
        "video": str(result.video_path),
        "data": str(result.data_path),
    }), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

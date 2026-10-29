import subprocess

import numpy as np
import pytest
from PIL import Image

from pipeline import bundle, frames

W, H = 64, 96


def _encode(path, raw_frames, pix_fmt="bgra", codec_args=("-c:v", "ffv1", "-g", "1")):
    proc = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", pix_fmt,
            "-s", f"{W}x{H}", "-r", str(frames.FPS), "-i", "-", *codec_args, str(path),
        ],
        stdin=subprocess.PIPE,
    )
    for frame in raw_frames:
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    assert proc.wait() == 0


def _grey_frames(levels):
    out = []
    for level in levels:
        frame = np.zeros((H, W, 4), np.uint8)
        frame[..., :3] = level
        frame[..., 3] = 255
        out.append(frame)
    return out


def _levels(path, count=None):
    return [int(f[..., 0].mean().round()) for f in frames.read_frames(path, W, H, count=count)]


def test_png_alpha_is_detected_and_a_still_becomes_ten_seconds(tmp_path):
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[20:60, 20:40] = [200, 100, 50, 255]
    Image.fromarray(rgba, "RGBA").save(tmp_path / "still.png")
    Image.fromarray(rgba[..., :3], "RGB").save(tmp_path / "still.jpg")

    assert frames.probe_source(tmp_path / "still.png").has_alpha
    assert not frames.probe_source(tmp_path / "still.jpg").has_alpha

    info = frames.prepare_video(tmp_path / "still.png", tmp_path / "prep.mkv")
    assert info.is_image and info.has_alpha
    count = frames.count_frames(tmp_path / "prep.mkv", info.width, info.height)
    assert count == frames.STILL_SECONDS * frames.FPS
    first = next(frames.read_frames(tmp_path / "prep.mkv", info.width, info.height, count=1))
    assert first[0, 0, 3] == 0 and first[30, 30, 3] == 255


def test_png_with_bytes_after_iend_still_finishes(tmp_path):
    # C2PA-signed exports carry trailing data; re-demuxing it each loop never yields a frame.
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[20:60, 20:40] = [200, 100, 50, 255]
    path = tmp_path / "signed.png"
    Image.fromarray(rgba, "RGBA").save(path)
    with path.open("ab") as f:
        f.write(b"\xb3\xd2\x42\x30" * 8)

    info = frames.prepare_video(path, tmp_path / "prep.mkv")
    assert frames.count_frames(tmp_path / "prep.mkv", info.width, info.height) == (
        frames.STILL_SECONDS * frames.FPS
    )


def test_vp9_alpha_webm_is_decoded_with_its_alpha(tmp_path):
    src = np.zeros((H, W, 4), np.uint8)
    src[..., 3] = 0
    src[30:60, 20:40] = [10, 200, 10, 255]
    _encode(tmp_path / "a.webm", [src] * 5,
            codec_args=("-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0"))
    info = frames.probe_source(tmp_path / "a.webm")
    assert info.has_alpha and info.decoder == "libvpx-vp9"
    prepared = frames.prepare_video(tmp_path / "a.webm", tmp_path / "prep.mkv")
    first = next(frames.read_frames(tmp_path / "prep.mkv", prepared.width, prepared.height, count=1))
    assert first[2, 2, 3] < 20 and first[45, 30, 3] > 230


def test_seam_difference_separates_a_loop_from_a_jump(tmp_path):
    _encode(tmp_path / "loop.mkv", _grey_frames([50, 90, 130, 90, 50]))
    _encode(tmp_path / "jump.mkv", _grey_frames([50, 90, 130, 170, 210]))
    assert frames.loop_seam_difference(tmp_path / "loop.mkv", W, H, 5) < 1
    assert frames.loop_seam_difference(tmp_path / "jump.mkv", W, H, 5) > frames.LOOP_SEAM_THRESHOLD


def test_ping_pong_plays_back_without_repeating_the_ends(tmp_path, monkeypatch):
    # A chunk smaller than the clip proves the reversed half is stitched in order.
    monkeypatch.setattr(frames, "REVERSE_CHUNK", 2)
    levels = [10, 40, 70, 100, 130, 160]
    _encode(tmp_path / "src.mkv", _grey_frames(levels))
    written = frames.write_ping_pong(tmp_path / "src.mkv", tmp_path / "pp.mkv", W, H, len(levels))
    assert written == 10
    assert _levels(tmp_path / "pp.mkv") == levels + [130, 100, 70, 40]


def test_transparent_detection_background_is_flat_grey():
    frame = np.zeros((4, 4, 4), np.uint8)
    frame[0, 0] = [0, 0, 255, 255]
    flat = frames.flatten_for_detection(frame)
    assert (flat[0, 0] == [0, 0, 255]).all()
    assert (flat[3, 3] == frames.DETECTION_BACKGROUND).all()


def test_marker_is_opaque_on_transparent_frames():
    frame = np.zeros((8, 8, 4), np.uint8)
    bundle.stamp_marker(frame, 3)
    assert (frame[0:4, 4:8, :3] == 120).all()
    assert (frame[0:4, 4:8, 3] == 255).all()
    assert (frame[4:, :, 3] == 0).all()


@pytest.mark.parametrize("alpha", [True, False])
def test_transcode_keeps_alpha_only_for_transparent_sources(tmp_path, alpha):
    src = _grey_frames([60] * 8)
    for frame in src:
        frame[40:, :, 3] = 0 if alpha else 255
    _encode(tmp_path / "src.mkv", src)
    count = bundle.transcode_with_marker(
        tmp_path / "src.mkv", tmp_path / "01.webm", W, H, 8, alpha=alpha,
    )
    assert count == 8
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream_tags=alpha_mode",
         "-of", "csv=p=0", str(tmp_path / "01.webm")],
        capture_output=True, text=True,
    ).stdout.strip()
    assert (probe == "1") is alpha

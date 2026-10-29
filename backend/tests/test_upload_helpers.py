"""Shared upload limit helpers: bounded reads, image, media and zip checks."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import wave
import zipfile

import pytest

from app.utils.document_checks import check_zip_archive, require_document_suffix
from app.utils.images import validate_image, validate_image_file
from app.utils.media import probe_media, require_duration
from app.utils.upload import (
    UnsupportedUploadError,
    UploadTooLargeError,
    persist_upload_to_tempfile,
    read_upload_limited,
)


class _CountingUpload:
    """UploadFile stand-in that counts how many chunks were pulled."""

    def __init__(self, chunks: int, chunk_size: int = 1024 * 1024) -> None:
        self.remaining = chunks
        self.chunk_size = chunk_size
        self.reads = 0

    async def read(self, size: int = -1) -> bytes:
        self.reads += 1
        if self.remaining <= 0:
            return b""
        self.remaining -= 1
        return b"x" * self.chunk_size


@pytest.mark.asyncio
async def test_read_upload_limited_stops_at_the_first_chunk_over_the_limit():
    upload = _CountingUpload(chunks=100)
    with pytest.raises(UploadTooLargeError) as caught:
        await read_upload_limited(upload, max_bytes=2 * 1024 * 1024 + 1, label="圖片")
    assert upload.reads == 3
    assert str(caught.value) == "圖片超過大小上限（2.0 MB）"


@pytest.mark.asyncio
async def test_persist_upload_stops_early_and_removes_the_partial_file(tmp_path):
    upload = _CountingUpload(chunks=100)
    with pytest.raises(UploadTooLargeError):
        await persist_upload_to_tempfile(
            upload, suffix=".bin", max_bytes=1024 * 1024, dir=str(tmp_path),
        )
    assert upload.reads == 2
    assert os.listdir(tmp_path) == []


def _png(width: int, height: int) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("L", (width, height)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_validate_image_sniffs_png_and_bounds_the_longest_side(tmp_path):
    assert validate_image(_png(8, 8), max_side=8) == "image/png"
    with pytest.raises(UploadTooLargeError):
        validate_image(_png(9, 1), max_side=8)
    path = tmp_path / "x.bin"
    path.write_bytes(_png(2, 2))
    assert validate_image_file(str(path), max_side=8) == "image/png"


@pytest.mark.parametrize(
    "payload",
    [b"GIF89a", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"\x89PNG\r\n\x1a\ntruncated"],
)
def test_validate_image_rejects_other_or_broken_content(payload):
    with pytest.raises(UnsupportedUploadError):
        validate_image(payload, max_side=8192)


def test_zip_guard_counts_entries_and_declared_size():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("a.xml", b"\0" * 4096)
        archive.writestr("b.xml", b"")
    check_zip_archive(io.BytesIO(buffer.getvalue()), max_uncompressed_bytes=4096, max_entries=2)
    with pytest.raises(UploadTooLargeError):
        check_zip_archive(io.BytesIO(buffer.getvalue()), max_uncompressed_bytes=4095, max_entries=2)
    with pytest.raises(UploadTooLargeError):
        check_zip_archive(io.BytesIO(buffer.getvalue()), max_uncompressed_bytes=4096, max_entries=1)
    with pytest.raises(UnsupportedUploadError):
        check_zip_archive(io.BytesIO(b"PK not really"), max_uncompressed_bytes=1, max_entries=1)


def test_document_suffix_whitelist():
    assert require_document_suffix("Report.PDF") == ".pdf"
    with pytest.raises(UnsupportedUploadError):
        require_document_suffix("macro.docm")


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="ffprobe not installed")
def test_probe_media_reads_real_audio_and_rejects_garbage(tmp_path):
    clip = tmp_path / "clip.wav"
    with wave.open(str(clip), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 4000)
    probe = probe_media(str(clip))
    assert probe.has_audio and not probe.has_video
    assert probe.duration_seconds == pytest.approx(0.5, abs=0.05)
    require_duration(probe, max_seconds=1, what="音檔")
    with pytest.raises(UploadTooLargeError, match="音檔長度超過上限"):
        require_duration(probe, max_seconds=0.25, what="音檔")

    garbage = tmp_path / "garbage.mp4"
    garbage.write_bytes(b"\0" * 256)
    with pytest.raises(UnsupportedUploadError):
        probe_media(str(garbage))


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_probe_media_reports_video_duration(tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi",
            "-i", "color=c=red:s=32x32:d=2", "-pix_fmt", "yuv420p", str(clip),
        ],
        check=True,
        timeout=60,
    )
    probe = probe_media(str(clip))
    assert probe.has_video
    assert probe.duration_seconds == pytest.approx(2, abs=0.2)

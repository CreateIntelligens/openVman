"""Identify uploaded images by their bytes and bound their pixel size."""

from __future__ import annotations

import io
import warnings
from typing import IO

from PIL import Image

from app.utils.upload import UnsupportedUploadError, UploadTooLargeError

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"

IMAGE_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def sniff_image_mime(data: bytes) -> str | None:
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image(data: bytes, *, max_side: int) -> str:
    """Return the sniffed MIME type of a png/jpeg/webp image within ``max_side``."""
    mime = sniff_image_mime(data)
    if mime is None:
        raise UnsupportedUploadError("圖片必須是 PNG、JPEG 或 WebP")
    _check_dimensions(io.BytesIO(data), max_side=max_side)
    return mime


def validate_image_file(path: str, *, max_side: int) -> str:
    """Same as :func:`validate_image` without loading the whole file."""
    with open(path, "rb") as handle:
        head = handle.read(16)
    mime = sniff_image_mime(head)
    if mime is None:
        raise UnsupportedUploadError("圖片必須是 PNG、JPEG 或 WebP")
    _check_dimensions(path, max_side=max_side)
    return mime


def _check_dimensions(source: str | IO[bytes], *, max_side: int) -> None:
    too_large = UploadTooLargeError(0, f"圖片尺寸超過上限（最長邊 {max_side} px）")
    try:
        # Image.open 只讀檔頭，不解碼像素；炸彈圖在這裡就會被尺寸擋下。
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(source) as image:
                width, height = image.size
    except Image.DecompressionBombError as exc:
        raise too_large from exc
    except (OSError, ValueError) as exc:
        raise UnsupportedUploadError("圖片內容無法讀取") from exc
    if max(width, height) > max_side:
        raise too_large

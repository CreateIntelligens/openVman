"""Validation for Avatar background uploads."""

from __future__ import annotations

import re

_BACKGROUND_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class InvalidBackgroundId(ValueError):
    """background_id 格式不合法。"""


class InvalidBackgroundUpload(ValueError):
    """背景圖副檔名或內容不合法。"""


def normalize_background_id(background_id: str | None) -> str:
    text = (background_id or "").strip()
    if not _BACKGROUND_ID_RE.match(text):
        raise InvalidBackgroundId("background_id 格式不合法（僅允許英數與 . _ -，長度 1-64）")
    if text in {".", ".."}:
        raise InvalidBackgroundId("background_id 不可為 . 或 ..")
    return text


def validate_image_bytes(data: bytes, *, filename: str) -> tuple[str, str]:
    lower = filename.lower()
    suffix = next((ext for ext in _SUPPORTED_EXTENSIONS if lower.endswith(ext)), "")
    if not suffix:
        raise InvalidBackgroundUpload("背景圖必須是 .png、.jpg、.jpeg 或 .webp")

    if suffix == ".png":
        if not data.startswith(_PNG_MAGIC):
            raise InvalidBackgroundUpload("背景圖內容不是有效的 png")
        return ".png", "image/png"

    if suffix in {".jpg", ".jpeg"}:
        if not data.startswith(_JPEG_MAGIC):
            raise InvalidBackgroundUpload("背景圖內容不是有效的 jpeg")
        return ".jpg", "image/jpeg"

    if not (data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP"):
        raise InvalidBackgroundUpload("背景圖內容不是有效的 webp")
    return ".webp", "image/webp"

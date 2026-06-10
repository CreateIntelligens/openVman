"""Validation for Avatar character uploads."""

from __future__ import annotations

import re

_CHAR_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_WEBM_MAGIC = b"\x1a\x45\xdf\xa3"
_GZIP_MAGIC = b"\x1f\x8b"


class InvalidCharId(ValueError):
    """char_id 格式不合法。"""


class InvalidUpload(ValueError):
    """上傳檔案副檔名或內容不合法。"""


def normalize_char_id(char_id: str | None) -> str:
    text = (char_id or "").strip()
    if not _CHAR_ID_RE.match(text):
        raise InvalidCharId("char_id 格式不合法（僅允許英數與 . _ -，長度 1-64）")
    if text in {".", ".."}:
        raise InvalidCharId("char_id 不可為 . 或 ..")
    return text


def validate_video_bytes(data: bytes, *, filename: str) -> None:
    if not filename.lower().endswith(".webm"):
        raise InvalidUpload("影片必須是 .webm 檔")
    if not data.startswith(_WEBM_MAGIC):
        raise InvalidUpload("影片內容不是有效的 webm（EBML magic 不符）")


def validate_data_bytes(data: bytes, *, filename: str) -> None:
    if not filename.lower().endswith(".gz"):
        raise InvalidUpload("驅動資料必須是 .gz 檔")
    if not data.startswith(_GZIP_MAGIC):
        raise InvalidUpload("驅動資料內容不是有效的 gzip（magic 不符）")

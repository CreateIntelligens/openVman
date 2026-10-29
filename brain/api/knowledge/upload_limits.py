"""Server-side upload limits for the Brain knowledge endpoints.

Backend 已經驗過一次；這裡是縱深防禦：大小邊讀邊數、raw 區只能寫進 raw/、
知識文件只能寫進 knowledge/，副檔名照 Backend 同一份清單。
"""

from __future__ import annotations

import struct
from pathlib import PurePosixPath

from fastapi import HTTPException, UploadFile

_CHUNK = 1024 * 1024

# 與 backend/app/utils/document_checks.py 的 DOCUMENT_SUFFIXES 一致。
RAW_UPLOAD_SUFFIXES = frozenset({
    ".md", ".markdown", ".txt", ".csv",
    ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm",
})


async def read_upload_limited(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"檔案超過大小上限（{max_bytes // (1024 * 1024)} MB）",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def require_target_under(target_dir: str, root: str) -> str:
    """Return ``target_dir`` normalised, or 400 if it leaves ``root``/."""
    cleaned = target_dir.strip().rstrip("/") or root
    parts = cleaned.split("/")
    if (
        cleaned.startswith("/")
        or "\\" in cleaned
        or ":" in cleaned
        or any(part in ("", ".", "..") for part in parts)
        or parts[0] != root
    ):
        raise HTTPException(status_code=400, detail=f"target_dir 必須位於 {root}/ 底下")
    return cleaned


def require_raw_suffix(filename: str, relative_path: str = "") -> None:
    for name in (filename, relative_path):
        if name and PurePosixPath(name).suffix.lower() not in RAW_UPLOAD_SUFFIXES:
            allowed = "、".join(sorted(RAW_UPLOAD_SUFFIXES))
            raise HTTPException(status_code=415, detail=f"不支援的文件格式，僅接受 {allowed}")


def sniff_image(data: bytes) -> tuple[str, int | None, int | None] | None:
    """Return (extension, width, height) from the header, or None if unknown.

    Brain 沒有 Pillow，這裡只解析檔頭。avif／ico 只認格式不讀尺寸
    （ico 本身最大 256 px；avif 仍受位元組上限約束）。
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24 and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return ".png", width, height
    if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return ".gif", width, height
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return ".webp", width, height
        if chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            width, height = struct.unpack("<HH", data[26:30])
            return ".webp", width & 0x3FFF, height & 0x3FFF
        if chunk == b"VP8L" and data[20:21] == b"\x2f":
            bits = int.from_bytes(data[21:25], "little")
            return ".webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        return None
    if data.startswith(b"\xff\xd8"):
        return _jpeg_size(data)
    if data.startswith(b"BM") and len(data) >= 26:
        width, height = struct.unpack("<ii", data[18:26])
        return ".bmp", abs(width), abs(height)
    if data.startswith(b"\x00\x00\x01\x00"):
        return ".ico", None, None
    if data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis", b"mif1"):
        return ".avif", None, None
    return None


def _jpeg_size(data: bytes) -> tuple[str, int, int] | None:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            return None
        marker = data[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        (length,) = struct.unpack(">H", data[index + 2:index + 4])
        # SOF0–SOF15（扣掉 DHT／JPG／DAC）帶影像尺寸。
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[index + 5:index + 9])
            return ".jpg", width, height
        index += 2 + length
    return None


_EXT_FAMILY = {".jpeg": ".jpg"}


def validate_qa_image(data: bytes, filename_ext: str, max_side: int) -> None:
    """Content must be a readable image whose magic matches the extension."""
    sniffed = sniff_image(data)
    claimed = _EXT_FAMILY.get(filename_ext, filename_ext)
    if sniffed is None or sniffed[0] != claimed:
        raise HTTPException(status_code=415, detail="圖片內容與副檔名不符，或無法辨識的圖片格式")
    _, width, height = sniffed
    if width is None or height is None:
        return
    if width <= 0 or height <= 0:
        raise HTTPException(status_code=415, detail="圖片內容無法讀取")
    if max(width, height) > max_side:
        raise HTTPException(status_code=413, detail=f"圖片尺寸超過上限（最長邊 {max_side} px）")

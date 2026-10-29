"""Shared upload helpers: bounded reads and the errors every upload route maps.

上傳一律邊讀邊數，超過上限立刻停，不把整個 body 讀進記憶體再比大小。
太大（位元組、時長、像素）回 413；格式不對或讀不出來回 415。
"""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress

from fastapi import HTTPException, UploadFile

UPLOAD_CHUNK_SIZE = 1024 * 1024
MIB = 1024 * 1024


def cleanup_temp_path(path: str | None) -> None:
    if path is None:
        return
    with suppress(FileNotFoundError):
        os.unlink(path)


def format_limit(limit_bytes: int) -> str:
    """Human-readable limit for error messages (whole MB when possible)."""
    if limit_bytes >= MIB:
        mb = limit_bytes / MIB
        return f"{mb:.0f} MB" if mb == int(mb) else f"{mb:.1f} MB"
    return f"{limit_bytes} bytes"


class UploadTooLargeError(Exception):
    """Raised when an upload exceeds a size, duration or dimension limit (413)."""

    def __init__(
        self, limit_bytes: int, message: str | None = None, *, label: str = "檔案",
    ) -> None:
        self.limit_bytes = limit_bytes
        self.message = message or f"{label}超過大小上限（{format_limit(limit_bytes)}）"
        super().__init__(self.message)


class UnsupportedUploadError(Exception):
    """Raised when an upload's real content is not an accepted format (415)."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


UploadLimitError = (UploadTooLargeError, UnsupportedUploadError)


def as_http_exception(exc: Exception) -> HTTPException:
    """Map a limit error to the 413 / 415 HTTPException routes raise."""
    status_code = 413 if isinstance(exc, UploadTooLargeError) else 415
    return HTTPException(status_code=status_code, detail=str(exc))


async def read_upload_limited(
    file: UploadFile, *, max_bytes: int, label: str = "檔案",
) -> bytes:
    """Read an upload into memory, stopping as soon as ``max_bytes`` is passed."""
    chunks: list[bytes] = []
    total_bytes = 0
    while chunk := await file.read(UPLOAD_CHUNK_SIZE):
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise UploadTooLargeError(max_bytes, label=label)
        chunks.append(chunk)
    return b"".join(chunks)


async def persist_upload_to_tempfile(
    file: UploadFile,
    *,
    suffix: str,
    max_bytes: int,
    dir: str | None = None,
    label: str = "檔案",
) -> tuple[str, int]:
    total_bytes = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=dir) as tmp:
        tmp_path = tmp.name
        try:
            while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise UploadTooLargeError(max_bytes, label=label)
                tmp.write(chunk)
        except BaseException:
            cleanup_temp_path(tmp_path)
            raise
    return tmp_path, total_bytes

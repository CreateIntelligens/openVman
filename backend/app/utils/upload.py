"""Shared upload helpers used by main.py and gateway routes."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress

from fastapi import UploadFile

UPLOAD_CHUNK_SIZE = 1024 * 1024


def cleanup_temp_path(path: str | None) -> None:
    if path is None:
        return
    with suppress(FileNotFoundError):
        os.unlink(path)


class UploadTooLargeError(Exception):
    """Raised when an uploaded file exceeds the configured limit."""

    def __init__(self, limit_bytes: int) -> None:
        super().__init__(f"uploaded file too large: limit={limit_bytes}")
        self.limit_bytes = limit_bytes


async def persist_upload_to_tempfile(
    file: UploadFile,
    *,
    suffix: str,
    max_bytes: int,
) -> tuple[str, int]:
    total_bytes = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
        try:
            while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise UploadTooLargeError(max_bytes)
                tmp.write(chunk)
        except Exception:
            cleanup_temp_path(tmp_path)
            raise
    return tmp_path, total_bytes

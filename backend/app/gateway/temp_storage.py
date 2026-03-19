"""Temporary file storage service for uploaded media."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import get_tts_config

logger = logging.getLogger("gateway.temp_storage")

_MIME_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


@dataclass(frozen=True)
class QuotaStatus:
    ok: bool
    usage_mb: float
    limit_mb: int


class TempStorageService:
    def __init__(self, base_dir: str | None = None) -> None:
        cfg = get_tts_config()
        self.base_dir = base_dir or cfg.gateway_temp_dir
        self._cleanup_task: asyncio.Task[None] | None = None
        Path(self.base_dir).mkdir(parents=True, exist_ok=True)

    # --- quota ---

    def check_quota(self) -> QuotaStatus:
        cfg = get_tts_config()
        usage_bytes = self._dir_size(self.base_dir)
        usage_mb = usage_bytes / (1024 * 1024)
        limit_mb = cfg.gateway_temp_dir_max_mb
        return QuotaStatus(
            ok=usage_mb < limit_mb,
            usage_mb=usage_mb,
            limit_mb=limit_mb,
        )

    # --- write ---

    def write_file(self, session_id: str, data: bytes, mime_type: str) -> str:
        if ".." in session_id or "/" in session_id or "%2F" in session_id:
            raise ValueError("INVALID_SESSION_ID: path traversal detected")

        ext = _MIME_EXT.get(mime_type, "bin")
        session_dir = os.path.join(self.base_dir, session_id)
        os.makedirs(session_dir, exist_ok=True)

        filename = f"{uuid.uuid4().hex}.{ext}"
        file_path = os.path.join(session_dir, filename)
        with open(file_path, "wb") as f:
            f.write(data)

        logger.info("temp_file_written path=%s session_id=%s", file_path, session_id)
        return file_path

    # --- validate ---

    def validate_file_size(self, size_bytes: int) -> bool:
        cfg = get_tts_config()
        limit_bytes = cfg.gateway_max_file_size_mb * 1024 * 1024
        return size_bytes <= limit_bytes

    # --- cleanup ---

    def cleanup_session(self, session_id: str) -> None:
        if ".." in session_id or "/" in session_id:
            return
        session_dir = os.path.join(self.base_dir, session_id)
        shutil.rmtree(session_dir, ignore_errors=True)
        logger.info("session_cleanup session_id=%s", session_id)

    def run_ttl_cleanup(self) -> None:
        cfg = get_tts_config()
        ttl_seconds = cfg.gateway_temp_ttl_min * 60
        now = time.time()
        try:
            for session_name in os.listdir(self.base_dir):
                session_path = os.path.join(self.base_dir, session_name)
                if not os.path.isdir(session_path):
                    continue
                for filename in os.listdir(session_path):
                    file_path = os.path.join(session_path, filename)
                    try:
                        mtime = os.path.getmtime(file_path)
                        age = now - mtime
                        if age > ttl_seconds:
                            os.unlink(file_path)
                            logger.info("temp_file_cleanup path=%s age_min=%d", file_path, int(age / 60))
                    except FileNotFoundError:
                        pass
        except FileNotFoundError:
            pass

    # --- background cleanup loop ---

    async def start_cleanup_loop(self) -> None:
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(5 * 60)
            self.run_ttl_cleanup()

    async def stop_cleanup_loop(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    # --- helpers ---

    def _dir_size(self, path: str) -> int:
        total = 0
        try:
            for entry in os.scandir(path):
                if entry.is_dir(follow_symlinks=False):
                    total += self._dir_size(entry.path)
                else:
                    total += entry.stat(follow_symlinks=False).st_size
        except FileNotFoundError:
            pass
        return total


_instance: TempStorageService | None = None


def get_temp_storage() -> TempStorageService:
    global _instance
    if _instance is None:
        _instance = TempStorageService()
    return _instance


def reset_temp_storage() -> None:
    global _instance
    _instance = None

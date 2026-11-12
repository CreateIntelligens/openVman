"""Temporary file storage service for uploaded media."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import get_tts_config
from app.utils.log_safe import log_safe

logger = logging.getLogger("gateway.temp_storage")

_SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
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

    def _session_dir(self, session_id: str) -> str:
        # 白名單取代黑名單：空字串或 "." 會把檔案寫在根目錄、TTL 清理掃不到，
        # cleanup_session("") 甚至會刪掉整個根目錄。
        if not _SESSION_ID_RE.fullmatch(session_id or ""):
            raise ValueError("INVALID_SESSION_ID: path traversal detected")
        base = os.path.realpath(self.base_dir)
        session_dir = os.path.normpath(os.path.join(base, session_id))
        if not session_dir.startswith(base + os.sep) or os.path.dirname(session_dir) != base:
            raise ValueError("INVALID_SESSION_ID: path traversal detected")
        return session_dir

    def write_file(self, session_id: str, data: bytes, mime_type: str) -> str:
        session_dir = self._session_dir(session_id)

        ext = _MIME_EXT.get(mime_type, "bin")
        os.makedirs(session_dir, exist_ok=True)

        filename = f"{uuid.uuid4().hex}.{ext}"
        file_path = os.path.join(session_dir, filename)
        with open(file_path, "wb") as f:
            f.write(data)

        logger.info("temp_file_written path=%s session_id=%s", file_path, session_id)
        return file_path

    # --- validate ---

    def store_file(self, session_id: str, source_path: str, mime_type: str) -> str:
        """Move an already-streamed upload into the session directory."""
        session_dir = self._session_dir(session_id)

        ext = _MIME_EXT.get(mime_type, "bin")
        os.makedirs(session_dir, exist_ok=True)
        file_path = os.path.join(session_dir, f"{uuid.uuid4().hex}.{ext}")
        shutil.move(source_path, file_path)
        logger.info("file_written path=%s", log_safe(file_path))
        return file_path

    def validate_file_size(self, size_bytes: int) -> bool:
        cfg = get_tts_config()
        limit_bytes = cfg.gateway_max_file_size_mb * 1024 * 1024
        return size_bytes <= limit_bytes

    # --- cleanup ---

    def cleanup_session(self, session_id: str) -> None:
        try:
            session_dir = self._session_dir(session_id)
        except ValueError:
            return
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

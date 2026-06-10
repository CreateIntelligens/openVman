"""Filesystem-backed store for Avatar character assets.

Layout (under base_dir):
    {char_id}/01.webm
    {char_id}/combined_data.json.gz
    {char_id}/meta.json   -> {"label", "created_at", "updated_at"}
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from app.avatar.validation import normalize_char_id

VIDEO_FILENAME = "01.webm"
DATA_FILENAME = "combined_data.json.gz"
META_FILENAME = "meta.json"


class CharacterExists(ValueError):
    """同名 char_id 已存在。"""


class CharacterNotFound(ValueError):
    """char_id 不存在。"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class AvatarStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _dir(self, char_id: str) -> Path:
        return self._base / char_id

    def exists(self, char_id: str) -> bool:
        return self._dir(normalize_char_id(char_id)).is_dir()

    def list_characters(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in sorted(self._base.iterdir()):
            if not path.is_dir():
                continue
            out.append(self._summary(path))
        return out

    def get_character(self, char_id: str) -> dict[str, Any]:
        cid = normalize_char_id(char_id)
        path = self._dir(cid)
        if not path.is_dir():
            raise CharacterNotFound(f"角色不存在：{cid}")
        return self._summary(path)

    def create_character(
        self,
        *,
        char_id: str,
        label: str,
        video_bytes: bytes,
        data_bytes: bytes,
    ) -> dict[str, Any]:
        cid = normalize_char_id(char_id)
        target = self._dir(cid)
        if target.exists():
            raise CharacterExists(f"角色已存在：{cid}")

        tmp = Path(tempfile.mkdtemp(dir=self._base, prefix=f".{cid}.tmp."))
        try:
            (tmp / VIDEO_FILENAME).write_bytes(video_bytes)
            (tmp / DATA_FILENAME).write_bytes(data_bytes)
            now = _now()
            self._write_meta(
                tmp,
                {"label": label.strip() or cid, "created_at": now, "updated_at": now},
            )
            os.rename(tmp, target)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return self._summary(target)

    def delete_character(self, char_id: str) -> None:
        cid = normalize_char_id(char_id)
        path = self._dir(cid)
        if not path.is_dir():
            raise CharacterNotFound(f"角色不存在：{cid}")
        shutil.rmtree(path)

    def rename_character(self, char_id: str, new_char_id: str) -> dict[str, Any]:
        cid = normalize_char_id(char_id)
        new_cid = normalize_char_id(new_char_id)
        src = self._dir(cid)
        dst = self._dir(new_cid)
        if not src.is_dir():
            raise CharacterNotFound(f"角色不存在：{cid}")
        if cid != new_cid and dst.exists():
            raise CharacterExists(f"角色已存在：{new_cid}")
        if cid != new_cid:
            os.rename(src, dst)
            self._touch_meta(dst)
        return self._summary(dst)

    def _summary(self, path: Path) -> dict[str, Any]:
        meta = self._read_meta(path)
        video = path / VIDEO_FILENAME
        data = path / DATA_FILENAME
        size = 0
        for f in (video, data):
            if f.exists():
                size += f.stat().st_size
        return {
            "char_id": path.name,
            "label": meta.get("label", path.name),
            "has_video": video.exists(),
            "has_data": data.exists(),
            "size_bytes": size,
            "updated_at": meta.get("updated_at", ""),
        }

    def _read_meta(self, path: Path) -> dict[str, Any]:
        meta_path = path / META_FILENAME
        if not meta_path.exists():
            return {}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _touch_meta(self, path: Path) -> None:
        meta = self._read_meta(path)
        meta["updated_at"] = _now()
        meta.setdefault("label", path.name)
        self._write_meta(path, meta)

    def _write_meta(self, path: Path, meta: dict[str, Any]) -> None:
        (path / META_FILENAME).write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )

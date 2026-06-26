"""Filesystem-backed store for Avatar stage background images."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from app.avatar.background_validation import (
    normalize_background_id,
    validate_image_bytes,
)

META_FILENAME = "meta.json"
IMAGE_BASENAME = "image"
IMAGE_SUFFIXES = (".png", ".jpg", ".webp")


class BackgroundExists(ValueError):
    """同名 background_id 已存在。"""


class BackgroundNotFound(ValueError):
    """background_id 不存在。"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class AvatarBackgroundStore:
    def __init__(self, base_dir: str | Path, url_prefix: str = "/backgrounds") -> None:
        self._base = Path(base_dir)
        self._url_prefix = url_prefix.rstrip("/")
        self._base.mkdir(parents=True, exist_ok=True)

    def _dir(self, background_id: str) -> Path:
        return self._base / background_id

    def exists(self, background_id: str) -> bool:
        return self._dir(normalize_background_id(background_id)).is_dir()

    def list_backgrounds(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in sorted(self._base.iterdir()):
            if path.is_dir():
                out.append(self._summary(path))
        return out

    def get_background(self, background_id: str) -> dict[str, Any]:
        bid = normalize_background_id(background_id)
        path = self._dir(bid)
        if not path.is_dir():
            raise BackgroundNotFound(f"背景不存在：{bid}")
        return self._summary(path)

    def create_background(
        self,
        *,
        background_id: str,
        label: str,
        image_bytes: bytes,
        filename: str,
    ) -> dict[str, Any]:
        bid = normalize_background_id(background_id)
        suffix, mime_type = validate_image_bytes(image_bytes, filename=filename)
        target = self._dir(bid)
        if target.exists():
            raise BackgroundExists(f"背景已存在：{bid}")

        tmp = Path(tempfile.mkdtemp(dir=self._base, prefix=f".{bid}.tmp."))
        try:
            (tmp / f"{IMAGE_BASENAME}{suffix}").write_bytes(image_bytes)
            now = _now()
            self._write_meta(
                tmp,
                {
                    "label": label.strip() or bid,
                    "mime_type": mime_type,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            os.rename(tmp, target)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return self._summary(target)

    def delete_background(self, background_id: str) -> None:
        bid = normalize_background_id(background_id)
        path = self._dir(bid)
        if not path.is_dir():
            raise BackgroundNotFound(f"背景不存在：{bid}")
        shutil.rmtree(path)

    def update_label(self, background_id: str, label: str) -> dict[str, Any]:
        bid = normalize_background_id(background_id)
        path = self._dir(bid)
        if not path.is_dir():
            raise BackgroundNotFound(f"背景不存在：{bid}")
        meta = self._read_meta(path)
        meta["label"] = label.strip()
        meta["updated_at"] = _now()
        self._write_meta(path, meta)
        return self._summary(path)

    def _image_path(self, path: Path) -> Path | None:
        for suffix in IMAGE_SUFFIXES:
            candidate = path / f"{IMAGE_BASENAME}{suffix}"
            if candidate.exists():
                return candidate
        return None

    def _summary(self, path: Path) -> dict[str, Any]:
        meta = self._read_meta(path)
        image = self._image_path(path)
        mime_type = meta.get("mime_type", "")
        size = image.stat().st_size if image else 0
        url = f"{self._url_prefix}/{path.name}/{image.name}" if image else ""
        return {
            "background_id": path.name,
            "label": meta.get("label", path.name),
            "url": url,
            "mime_type": mime_type,
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

    def _write_meta(self, path: Path, meta: dict[str, Any]) -> None:
        (path / META_FILENAME).write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )

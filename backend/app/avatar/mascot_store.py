"""Filesystem-backed store for right-corner mascot assets.

Mascots can use an uploaded VRM or reference an existing video character.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from app.avatar.mascot_validation import extract_vrm_thumbnail, normalize_mascot_id

MODEL_FILENAME = "model.vrm"
THUMBNAIL_FILENAME = "thumbnail.png"
META_FILENAME = "meta.json"
# 影片型小助理沒有模型檔，只在 meta.json 記錄引擎與對應的 avatar 角色 id。
VIDEO_ENGINE = "video"
logger = logging.getLogger("backend.mascots")

BUILTIN_MASCOTS: tuple[dict[str, Any], ...] = (
    {
        "mascot_id": "haru-live2d",
        "label": "Haru",
        "engine": "2d",
        "model_url": "https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display/test/assets/haru/haru_greeter_t03.model3.json",
        "vrm_url": "",
        "character_id": "",
        "thumbnail_url": "",
        "fit": "half",
        "builtin": True,
        "size_bytes": 0,
        "updated_at": "",
    },
    {
        "mascot_id": "qqman",
        "label": "Frieren",
        "engine": "3d",
        "model_url": "",
        "vrm_url": "/static/mascots/qqman/model.vrm",
        "character_id": "",
        "thumbnail_url": "",
        "fit": "",
        "builtin": True,
        "size_bytes": 0,
        "updated_at": "",
    },
    {
        "mascot_id": "vrm-sample",
        "label": "VRM 3D",
        "engine": "3d",
        "model_url": "",
        "vrm_url": "https://cdn.jsdelivr.net/gh/pixiv/three-vrm@dev/packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm",
        "character_id": "",
        "thumbnail_url": "",
        "fit": "",
        "builtin": True,
        "size_bytes": 0,
        "updated_at": "",
    },
)

_BUILTIN_IDS = frozenset(mascot["mascot_id"] for mascot in BUILTIN_MASCOTS)


class MascotExists(ValueError):
    """同名 mascot_id 已存在。"""


class MascotNotFound(ValueError):
    """mascot_id 不存在或不可修改。"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class MascotStore:
    def __init__(self, base_dir: str | Path, url_prefix: str = "/static/mascots") -> None:
        self._base = Path(base_dir)
        self._url_prefix = url_prefix.rstrip("/")
        self._base.mkdir(parents=True, exist_ok=True)

    def _dir(self, mascot_id: str) -> Path:
        return self._base / mascot_id

    def exists(self, mascot_id: str) -> bool:
        mid = normalize_mascot_id(mascot_id)
        return mid in _BUILTIN_IDS or self._dir(mid).is_dir()

    def list_mascots(self) -> list[dict[str, Any]]:
        out = []
        for mascot in BUILTIN_MASCOTS:
            out.append(self._builtin_summary(mascot))
        for path in sorted(self._base.iterdir()):
            if path.is_dir() and path.name not in _BUILTIN_IDS:
                out.append(self._summary(path))
        return out

    def get_mascot(self, mascot_id: str) -> dict[str, Any]:
        mid = normalize_mascot_id(mascot_id)
        for mascot in BUILTIN_MASCOTS:
            if mascot["mascot_id"] == mid:
                return self._builtin_summary(mascot)
        path = self._dir(mid)
        if not path.is_dir():
            raise MascotNotFound(f"吉祥物不存在：{mid}")
        return self._summary(path)

    def create_mascot(
        self,
        *,
        mascot_id: str,
        label: str,
        vrm_bytes: bytes,
        thumbnail_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        mid = normalize_mascot_id(mascot_id)
        target = self._dir(mid)
        if mid in _BUILTIN_IDS or target.exists():
            raise MascotExists(f"吉祥物已存在：{mid}")

        tmp = Path(tempfile.mkdtemp(dir=self._base, prefix=f".{mid}.tmp."))
        try:
            (tmp / MODEL_FILENAME).write_bytes(vrm_bytes)
            if not thumbnail_bytes:
                thumbnail_bytes = self._extract_thumbnail(vrm_bytes, "extract")
            if thumbnail_bytes:
                (tmp / THUMBNAIL_FILENAME).write_bytes(thumbnail_bytes)
            now = _now()
            self._write_meta(
                tmp,
                {
                    "label": label.strip() or mid,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            os.rename(tmp, target)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return self._summary(target)

    def create_video_mascot(
        self,
        *,
        mascot_id: str,
        label: str,
        character_id: str,
    ) -> dict[str, Any]:
        """Register an existing video avatar character as a mascot.

        The character assets stay in the avatar store; the mascot directory only
        carries meta.json so listing, renaming, and thumbnails work the same way
        as uploaded VRM mascots.
        """
        mid = normalize_mascot_id(mascot_id)
        target = self._dir(mid)
        if mid in _BUILTIN_IDS or target.exists():
            raise MascotExists(f"吉祥物已存在：{mid}")

        tmp = Path(tempfile.mkdtemp(dir=self._base, prefix=f".{mid}.tmp."))
        try:
            now = _now()
            self._write_meta(
                tmp,
                {
                    "label": label.strip() or mid,
                    "engine": VIDEO_ENGINE,
                    "character_id": character_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            os.rename(tmp, target)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return self._summary(target)

    def delete_mascot(self, mascot_id: str) -> None:
        mid = normalize_mascot_id(mascot_id)
        path = self._dir(mid)
        if mid in _BUILTIN_IDS or not path.is_dir():
            raise MascotNotFound(f"吉祥物不存在或不可刪除：{mid}")
        shutil.rmtree(path)

    def update_label(self, mascot_id: str, label: str) -> dict[str, Any]:
        mid = normalize_mascot_id(mascot_id)
        path = self._dir(mid)
        if mid in _BUILTIN_IDS or not path.is_dir():
            raise MascotNotFound(f"吉祥物不存在或不可修改：{mid}")
        meta = self._read_meta(path)
        meta["label"] = label.strip()
        meta["updated_at"] = _now()
        self._write_meta(path, meta)
        return self._summary(path)

    def update_thumbnail(self, mascot_id: str, thumbnail_bytes: bytes) -> dict[str, Any]:
        mid = normalize_mascot_id(mascot_id)
        path = self._dir(mid)
        path.mkdir(parents=True, exist_ok=True)
        (path / THUMBNAIL_FILENAME).write_bytes(thumbnail_bytes)
        logger.info(
            "Successfully saved real mascot snapshot for %s, size: %d bytes",
            mid,
            len(thumbnail_bytes),
        )
        if mid in _BUILTIN_IDS:
            return {"thumbnail_url": f"{self._url_prefix}/{mid}/{THUMBNAIL_FILENAME}"}
        meta = self._read_meta(path)
        meta["updated_at"] = _now()
        self._write_meta(path, meta)
        return self._summary(path)

    def _summary(self, path: Path) -> dict[str, Any]:
        meta = self._read_meta(path)
        model = path / MODEL_FILENAME
        thumb = path / THUMBNAIL_FILENAME

        self._ensure_thumbnail(path, model, thumb)

        is_video = meta.get("engine") == VIDEO_ENGINE
        return {
            "mascot_id": path.name,
            "label": meta.get("label", path.name),
            "engine": VIDEO_ENGINE if is_video else "3d",
            "model_url": "",
            "vrm_url": (
                ""
                if is_video
                else f"{self._url_prefix}/{path.name}/{MODEL_FILENAME}"
            ),
            "character_id": str(meta.get("character_id", "")) if is_video else "",
            "thumbnail_url": (
                f"{self._url_prefix}/{path.name}/{THUMBNAIL_FILENAME}"
                if thumb.exists()
                else ""
            ),
            "fit": "",
            "builtin": False,
            "size_bytes": model.stat().st_size if model.exists() else 0,
            "updated_at": meta.get("updated_at", ""),
        }

    def _builtin_summary(self, mascot: dict[str, Any]) -> dict[str, Any]:
        summary = dict(mascot)
        mascot_id = str(summary["mascot_id"])
        thumb = self._dir(mascot_id) / THUMBNAIL_FILENAME
        if thumb.exists():
            summary["thumbnail_url"] = (
                f"{self._url_prefix}/{mascot_id}/{THUMBNAIL_FILENAME}"
            )
        return summary

    def _extract_thumbnail(self, vrm_bytes: bytes, action: str) -> bytes | None:
        try:
            return extract_vrm_thumbnail(vrm_bytes)
        except Exception as exc:
            logger.warning("Failed to %s thumbnail from VRM: %s", action, exc)
            return None

    def _ensure_thumbnail(self, path: Path, model: Path, thumb: Path) -> None:
        if thumb.exists() or not model.exists():
            return

        try:
            vrm_bytes = model.read_bytes()
        except OSError as exc:
            logger.warning(
                "Failed to auto-repair thumbnail for existing mascot %s: %s",
                path.name,
                exc,
            )
            return

        thumb_bytes = self._extract_thumbnail(vrm_bytes, "auto-repair")
        if not thumb_bytes:
            return

        try:
            thumb.write_bytes(thumb_bytes)
        except OSError as exc:
            logger.warning(
                "Failed to auto-repair thumbnail for existing mascot %s: %s",
                path.name,
                exc,
            )

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

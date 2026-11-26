"""Per-project knowledge and answer settings.

分流由管理者在知識庫設定勾選，不看有哪些文件：醫院的文件可能只有中文，但仍要
開台語分流，才認得出使用者在講台語。至少一條、不一定要中文（純英文知識庫只勾
English）。只有一條就不分流，行為與以前相同。清單順序是優先順序：第一條是主要
語言，短句與判斷不出來的輸入、以及其他語言查不到時都歸它。
"""

from __future__ import annotations

import json
import re
from math import isfinite
from pathlib import Path
from typing import Any

from infra.file_lock import atomic_write_text, file_lock
from infra.project_context import resolve_project_context
from memory.language_detect import DEFAULT_LANGUAGE, LANGUAGES

KB_SETTINGS_FILENAME = ".kb_settings.json"
# 回答要在幾秒內念完；0 是不限制（例如 ESG 要照抄完整 QA 答案）。換成各語言字數見
# core/prompt_templates.reply_length_line。
DEFAULT_REPLY_SECONDS = 20
MAX_REPLY_SECONDS = 120
_FEATURE_FIELDS = ("memory_enabled", "graph_enabled")
# 每則回覆都附的專案層級附件：聯絡圖片（例如 QR code）與型錄網址。
CATALOG_URL_MAX_CHARS = 500
# QA 圖片上傳產生的代號：uuid 加副檔名。只收這種，設定不能指到工作區裡的任意檔案。
_REPLY_IMAGE_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(png|jpe?g|webp|gif|bmp|avif)"
)


def _path(project_id: str) -> Path:
    return resolve_project_context(project_id).workspace_root / KB_SETTINGS_FILENAME


def _read_settings(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


# 每題都會讀；檔案被寫過時修改時間、大小或 inode 會變，沒變就用上次的結果。
_settings_cache: dict[Path, tuple[tuple[int, int, int], dict[str, Any]]] = {}


def _normalize_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    values = raw or {}
    return {
        "language_routes": _normalize_routes(values.get("language_routes")),
        "reply_seconds": _normalize_seconds(values.get("reply_seconds")),
        # 舊專案缺欄位時沿用開啟，讀不到有效設定或明寫非布林值時關閉。
        **{field: raw is not None and values.get(field, True) is True for field in _FEATURE_FIELDS},
    }


def load_kb_settings(project_id: str = "default") -> dict[str, Any]:
    path = _path(project_id)
    try:
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
    except FileNotFoundError:
        return _normalize_settings({})
    except OSError:
        return _normalize_settings(None)
    cached = _settings_cache.get(path)
    if cached is not None and cached[0] == signature:
        settings = cached[1]
    else:
        try:
            raw = _read_settings(path)
        except OSError:
            raw = None
        settings = _normalize_settings(raw)
        _settings_cache[path] = (signature, settings)
    return {**settings, "language_routes": list(settings["language_routes"])}


def _update_settings(project_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    path = _path(project_id)
    with file_lock(path):
        raw = _read_settings(path)
        # 檔案損壞時讀到的是關閉；存別的欄位時把關閉寫明，不然缺欄位會被當成舊專案而打開。
        base = raw if raw is not None else {field: False for field in _FEATURE_FIELDS}
        settings = {
            key: value for key, value in {**base, **updates}.items()
            if not (key in updates and updates[key] is None)
        }
        atomic_write_text(path, json.dumps(settings, ensure_ascii=False, indent=2))
    return _normalize_settings(settings)


def save_kb_settings(
    project_id: str,
    *,
    language_routes: list[str] | None = None,
    reply_seconds: int | None = None,
) -> dict[str, Any]:
    """Save the settings; a field left as None keeps its stored value."""
    updates: dict[str, Any] = {}
    if language_routes is not None:
        updates["language_routes"] = _normalize_routes(language_routes)
    if reply_seconds is not None:
        updates["reply_seconds"] = _normalize_seconds(reply_seconds)
    return _update_settings(project_id, updates)


def save_project_features(
    project_id: str, *, memory_enabled: bool | None = None, graph_enabled: bool | None = None,
) -> dict[str, Any]:
    return _update_settings(project_id, {
        field: value
        for field, value in zip(_FEATURE_FIELDS, (memory_enabled, graph_enabled))
        if value is not None
    })


def memory_enabled(project_id: str = "default") -> bool:
    return load_kb_settings(project_id)["memory_enabled"]


def reply_seconds(project_id: str = "default") -> int:
    return load_kb_settings(project_id)["reply_seconds"]


def _normalize_seconds(value: Any) -> int:
    # 沒設過（舊專案）用預設；設 0 是刻意不限制，要保留。
    if type(value) not in (int, float) or (isinstance(value, float) and not isfinite(value)):
        return DEFAULT_REPLY_SECONDS
    return max(0, min(MAX_REPLY_SECONDS, int(value)))


def language_routes(project_id: str = "default") -> list[str]:
    return load_kb_settings(project_id)["language_routes"]


def _normalize_routes(value: Any) -> list[str]:
    # 順序就是優先順序，由後台排：第一條是主要語言（短句、判斷不出來、查不到時都歸它）。
    routes: list[str] = []
    for item in value if isinstance(value, list) else []:
        if str(item) in LANGUAGES and str(item) not in routes:
            routes.append(str(item))
    # 至少一條；什麼都沒勾（或舊資料）就當只有中文。
    return routes or [DEFAULT_LANGUAGE]


def primary_language(project_id: str = "default") -> str:
    """The project's main language for short or unclear input and for replies."""
    return language_routes(project_id)[0]


def fallback_route(project_id: str = "default") -> str:
    """The route other languages fall back to: the first ticked one."""
    return language_routes(project_id)[0]


def _valid_catalog_url(value: Any) -> str | None:
    from urllib.parse import urlsplit

    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > CATALOG_URL_MAX_CHARS or any(ch.isspace() for ch in cleaned):
        return None
    try:
        parts = urlsplit(cleaned)
        host = parts.hostname
    except ValueError:
        return None
    return cleaned if parts.scheme == "https" and host else None


def _valid_reply_image(value: Any) -> str | None:
    return value if isinstance(value, str) and _REPLY_IMAGE_RE.fullmatch(value) else None


def load_reply_links(project_id: str = "default") -> dict[str, str | None]:
    """The project's contact image id and catalogue url; never raises (runs on every reply)."""
    # 每則回覆都會跑：檔案被手改壞、專案代號不合法都只當作沒設，不能讓回覆失敗。
    try:
        raw = _read_settings(_path(project_id)) or {}
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "contact_image_id": _valid_reply_image(raw.get("contact_image_id")),
        "catalog_url": _valid_catalog_url(raw.get("catalog_url")),
    }


def save_reply_links(
    project_id: str, contact_image_id: str | None, catalog_url: str | None,
) -> dict[str, str | None]:
    """Replace both reply links; None clears one. Raises ValueError with a plain message."""
    from knowledge.qa_images import resolve_qa_image_path

    updates: dict[str, Any] = {"contact_image_id": None, "catalog_url": None}
    if contact_image_id is not None:
        if not _valid_reply_image(contact_image_id):
            raise ValueError("聯絡圖片必須是 QA 圖片上傳後拿到的圖片代號。")
        if resolve_qa_image_path(contact_image_id, project_id) is None:
            raise ValueError("找不到這張圖片，請先上傳到 QA 圖片。")
        updates["contact_image_id"] = contact_image_id
    if catalog_url is not None:
        valid = _valid_catalog_url(catalog_url)
        if valid is None:
            raise ValueError(f"型錄網址只收 https，長度 1 到 {CATALOG_URL_MAX_CHARS} 個字元。")
        updates["catalog_url"] = valid
    _update_settings(project_id, updates)
    return load_reply_links(project_id)

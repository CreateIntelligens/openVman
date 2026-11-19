"""Per-project knowledge and answer settings.

分流由管理者在知識庫設定勾選，不看有哪些文件：醫院的文件可能只有中文，但仍要
開台語分流，才認得出使用者在講台語。至少一條、不一定要中文（純英文知識庫只勾
English）。只有一條就不分流，行為與以前相同。清單順序是優先順序：第一條是主要
語言，短句與判斷不出來的輸入、以及其他語言查不到時都歸它。
"""

from __future__ import annotations

import json
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
        settings = {**base, **updates}
        atomic_write_text(path, json.dumps(settings, ensure_ascii=False, indent=2))
    return _normalize_settings(settings)


def save_kb_settings(
    project_id: str,
    *,
    language_routes: list[str],
    reply_seconds: int | None = None,
) -> dict[str, Any]:
    """Save the settings; ``reply_seconds`` None keeps the stored value."""
    updates = {"language_routes": _normalize_routes(language_routes)}
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

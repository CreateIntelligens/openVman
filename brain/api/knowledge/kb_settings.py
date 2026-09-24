"""Per-project knowledge base settings (language routes).

分流由管理者在知識庫設定勾選，不看有哪些文件：醫院的文件可能只有中文，但仍要
開台語分流，才認得出使用者在講台語。只勾中文就完全不分流，行為與以前相同。
"""

from __future__ import annotations

import json
from typing import Any

from knowledge.workspace import ensure_workspace_scaffold
from memory.language_detect import DEFAULT_LANGUAGE, LANGUAGES

KB_SETTINGS_FILENAME = ".kb_settings.json"


def _path(project_id: str):
    return ensure_workspace_scaffold(project_id) / KB_SETTINGS_FILENAME


def load_kb_settings(project_id: str = "default") -> dict[str, Any]:
    try:
        raw = json.loads(_path(project_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    return {"language_routes": _normalize_routes(raw.get("language_routes"))}


def save_kb_settings(project_id: str, *, language_routes: list[str]) -> dict[str, Any]:
    settings = {"language_routes": _normalize_routes(language_routes)}
    _path(project_id).write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return settings


def language_routes(project_id: str = "default") -> list[str]:
    return load_kb_settings(project_id)["language_routes"]


def _normalize_routes(value: Any) -> list[str]:
    chosen = {str(item) for item in value} if isinstance(value, list) else set()
    # 中文永遠是一條分流，也是其他語言查不到時的退路。
    chosen.add(DEFAULT_LANGUAGE)
    return [lang for lang in LANGUAGES if lang in chosen]

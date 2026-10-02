"""Per-project knowledge base settings (language routes, reply length).

分流由管理者在知識庫設定勾選，不看有哪些文件：醫院的文件可能只有中文，但仍要
開台語分流，才認得出使用者在講台語。至少一條、不一定要中文（純英文知識庫只勾
English）。只有一條就不分流，行為與以前相同。清單順序是優先順序：第一條是主要
語言，短句與判斷不出來的輸入、以及其他語言查不到時都歸它。
"""

from __future__ import annotations

import json
from typing import Any

from knowledge.workspace import ensure_workspace_scaffold
from memory.language_detect import DEFAULT_LANGUAGE, LANGUAGES

KB_SETTINGS_FILENAME = ".kb_settings.json"
# 回答要在幾秒內念完；0 是不限制（例如 ESG 要照抄完整 QA 答案）。換成各語言字數見
# core/prompt_templates.reply_length_line。
DEFAULT_REPLY_SECONDS = 20
MAX_REPLY_SECONDS = 120


def _path(project_id: str):
    return ensure_workspace_scaffold(project_id) / KB_SETTINGS_FILENAME


def load_kb_settings(project_id: str = "default") -> dict[str, Any]:
    try:
        raw = json.loads(_path(project_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    return {
        "language_routes": _normalize_routes(raw.get("language_routes")),
        "reply_seconds": _normalize_seconds(raw.get("reply_seconds")),
    }


def save_kb_settings(
    project_id: str,
    *,
    language_routes: list[str],
    reply_seconds: int | None = None,
) -> dict[str, Any]:
    """Save the settings; ``reply_seconds`` None keeps the stored value."""
    settings = {
        "language_routes": _normalize_routes(language_routes),
        "reply_seconds": (
            load_kb_settings(project_id)["reply_seconds"]
            if reply_seconds is None else _normalize_seconds(reply_seconds)
        ),
    }
    _path(project_id).write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return settings


def reply_seconds(project_id: str = "default") -> int:
    return load_kb_settings(project_id)["reply_seconds"]


def _normalize_seconds(value: Any) -> int:
    # 沒設過（舊專案）用預設；設 0 是刻意不限制，要保留。
    if isinstance(value, bool) or not isinstance(value, (int, float)):
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

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

active_persona_id: ContextVar[str] = ContextVar("brain_active_persona_id", default="default")
active_project_id: ContextVar[str] = ContextVar("brain_active_project_id", default="default")
active_user_message: ContextVar[str] = ContextVar("brain_active_user_message", default="")
# 這一輪的回覆模式（fast / standard / deep）。工具透過 mode_settings() 取用，
# 才能在同一個行程裡讓不同請求有不同的查詢深度。
active_reply_mode: ContextVar[str] = ContextVar("brain_active_reply_mode", default="")


def mode_settings() -> Any:
    """Settings with the active reply mode's overrides applied."""
    from config import get_settings
    from core.reply_modes import ModeSettings, resolve_mode

    base = get_settings()
    name = active_reply_mode.get()
    if not name:
        return base
    return ModeSettings(base, resolve_mode(name))

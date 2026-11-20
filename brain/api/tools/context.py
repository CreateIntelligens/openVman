from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

VENDOR_KNOWLEDGE_TOOLS = frozenset({"search_knowledge", "get_document"})
active_vendor_chat: ContextVar[bool] = ContextVar("brain_active_vendor_chat", default=False)
MEMORY_TOOLS = frozenset({"search_memory", "save_memory"})
GRAPH_TOOLS = frozenset({"graph_query", "graph_explain", "graph_status", "graphify:run"})
_WEB_TOOL_FLAGS = {
    "search_web": "url2md_search_enabled",
    "read_web_page": "url2md_read_enabled",
}
WEB_TOOLS = frozenset(_WEB_TOOL_FLAGS)
active_web_search_allowed: ContextVar[bool | None] = ContextVar(
    "brain_active_web_search_allowed", default=None,
)


def is_graph_tool(name: str) -> bool:
    return name in GRAPH_TOOLS or (
        name.startswith("proj:") and name.split(":", 2)[2:] == ["graphify:run"]
    )


active_persona_id: ContextVar[str] = ContextVar("brain_active_persona_id", default="default")
active_project_id: ContextVar[str] = ContextVar("brain_active_project_id", default="default")
active_user_message: ContextVar[str] = ContextVar("brain_active_user_message", default="")
# 前台 ASR 聽出的語言（例如台語 "nan"）；轉錄後的文字看不出來，查知識庫要靠它。
active_speech_language: ContextVar[str] = ContextVar("brain_active_speech_language", default="")
active_retrieval_language: ContextVar[str] = ContextVar("brain_active_retrieval_language", default="")
active_turn_decision_unavailable: ContextVar[bool] = ContextVar(
    "brain_active_turn_decision_unavailable", default=False,
)
# 這一輪的回覆模式（fast / standard / deep）。工具透過 mode_settings() 取用，
# 才能在同一個行程裡讓不同請求有不同的查詢深度。
active_reply_mode: ContextVar[str] = ContextVar("brain_active_reply_mode", default="")


@contextmanager
def bind_vendor_chat(vendor: bool):
    token = active_vendor_chat.set(vendor)
    try:
        yield
    finally:
        active_vendor_chat.reset(token)


@contextmanager
def bind_web_search(allowed: bool | None):
    token = active_web_search_allowed.set(allowed)
    try:
        yield
    finally:
        active_web_search_allowed.reset(token)


def web_search_permitted(allowed: bool | None, *, vendor: bool = False) -> bool:
    return allowed if allowed is not None else not vendor


def enabled_web_tools(
    config: Any, *, allowed: bool | None = None, vendor: bool = False,
) -> set[str]:
    if not web_search_permitted(allowed, vendor=vendor):
        return set()
    return {name for name, flag in _WEB_TOOL_FLAGS.items() if getattr(config, flag, True)}


def mode_settings() -> Any:
    """Settings with the active reply mode's overrides applied."""
    from config import get_settings
    from core.reply_modes import ModeSettings, resolve_mode

    base = get_settings()
    name = active_reply_mode.get()
    if not name:
        return base
    return ModeSettings(base, resolve_mode(name))

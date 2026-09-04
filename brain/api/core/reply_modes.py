"""Named depth presets for a chat turn.

一次回答要查多廣、允許模型來回幾輪，本質上是同一組旋鈕的不同設定。
把它們收成具名模式，使用者才能在「快」與「查得深」之間選，
而不是所有請求共用一套全域設定。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 對外的模式名稱。fast 只查知識庫求快；standard 是預設，知識庫與網路平行查
# 一輪；deep 允許多輪追查與讀更多頁，用時間換完整度。
FAST = "fast"
STANDARD = "standard"
DEEP = "deep"

DEFAULT_MODE = STANDARD


@dataclass(frozen=True, slots=True)
class ReplyMode:
    """One depth preset: how many tool rounds and how much reading is allowed."""

    name: str
    label: str
    max_followup_tool_rounds: int
    knowledge_merge_limit: int
    web_max_results: int
    web_read_max_urls: int
    # fast 模式不上網：知識庫查得到就答，查不到就說不知道。
    allow_web_search: bool = True


_MODES: dict[str, ReplyMode] = {
    FAST: ReplyMode(
        name=FAST,
        label="快速",
        max_followup_tool_rounds=0,
        knowledge_merge_limit=3,
        web_max_results=0,
        web_read_max_urls=1,
        allow_web_search=False,
    ),
    STANDARD: ReplyMode(
        name=STANDARD,
        label="標準",
        max_followup_tool_rounds=1,
        knowledge_merge_limit=5,
        web_max_results=8,
        web_read_max_urls=3,
    ),
    DEEP: ReplyMode(
        name=DEEP,
        label="深度",
        max_followup_tool_rounds=4,
        knowledge_merge_limit=10,
        web_max_results=12,
        web_read_max_urls=5,
    ),
}


def available_modes() -> list[ReplyMode]:
    return [_MODES[name] for name in (FAST, STANDARD, DEEP)]


def resolve_mode(name: str | None) -> ReplyMode:
    """Return the named mode, falling back to the default for anything unknown.

    模式名稱來自用戶端，不能信任；認不得就退回預設，而不是讓請求失敗。
    """
    if not name:
        return _MODES[DEFAULT_MODE]
    return _MODES.get(str(name).strip().lower(), _MODES[DEFAULT_MODE])


class ModeSettings:
    """A read-only settings view with the mode's overrides applied.

    直接改全域 settings 會污染其他併發請求，所以用一層薄的代理：認得的欄位
    回傳模式值，其餘一律透傳給真正的 settings。
    """

    __slots__ = ("_base", "_overrides")

    def __init__(self, base: Any, mode: ReplyMode) -> None:
        self._base = base
        self._overrides: dict[str, Any] = {
            "chat_max_followup_tool_rounds": mode.max_followup_tool_rounds,
            "knowledge_search_merge_limit": mode.knowledge_merge_limit,
            "web_search_max_results": mode.web_max_results,
            "web_read_max_urls": mode.web_read_max_urls,
        }

    def __getattr__(self, name: str) -> Any:
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._base, name)

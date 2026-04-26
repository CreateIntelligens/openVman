"""Route and context budget enforcement for the brain message pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from infra.reflection import compress_text
from protocol.message_envelope import BrainMessage, METADATA_ORIGINAL_USER_MESSAGE
from tools.actions import action_nl_hints

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class RouteDecision:
    """Immutable routing result for a brain message."""

    path: str       # "direct" | "rag" | "tool"
    skip_rag: bool
    skip_tools: bool
    forced_tool_name: str | None = None  # set by slash commands to force a specific tool call


_DIRECT_ROLES = frozenset({"system", "assistant", "control"})
_TOOL_QUERY_VERBS = (
    "查",
    "查詢",
    "查一下",
    "搜尋",
    "搜索",
    "找出",
    "找一下",
    "看看",
    "看一下",
    "列出",
    "讀取",
    "read",
    "search",
    "find",
    "list",
    "show",
    "open",
    "look up",
)
_TOOL_QUERY_TARGETS = (
    "知識庫",
    "文件",
    "文檔",
    "檔案",
    "docs",
    "doc",
    "readme",
    "repo",
    "repository",
    "專案",
    "project",
    "程式碼",
    "代碼",
    "代码",
    "code",
    "codebase",
    "圖譜",
    "graph",
    "工具",
    "tool",
    "tools",
    "skill",
    "skills",
)
_TOOL_MEMORY_HINTS = (
    "記住",
    "記下",
    "請記得",
    "remember",
    "save memory",
)
_TOOL_QUERY_VERBS_CASEFOLDED = tuple(verb.casefold() for verb in _TOOL_QUERY_VERBS)
_TOOL_QUERY_TARGETS_CASEFOLDED = tuple(target.casefold() for target in _TOOL_QUERY_TARGETS)
_TOOL_MEMORY_HINTS_CASEFOLDED = tuple(hint.casefold() for hint in _TOOL_MEMORY_HINTS)
_TOOL_ACTION_HINTS_CASEFOLDED = tuple(hint.casefold() for hint in action_nl_hints())
_SLASH_TOOL_REWRITE_PREFIX = "[系統指令] 請立即呼叫工具 `"


def route_message(brain_message: BrainMessage) -> RouteDecision:
    """Decide the processing path based on message role."""
    if brain_message.role in _DIRECT_ROLES:
        return RouteDecision(path="direct", skip_rag=True, skip_tools=True)
    if brain_message.role == "tool":
        return RouteDecision(path="tool", skip_rag=True, skip_tools=False)
    if _is_forced_tool_call(brain_message):
        tool_name = _extract_forced_tool_name(brain_message.content)
        if tool_name is None:
            logger.warning("forced tool call detected but could not extract tool name from: %r", brain_message.content[:80])
        return RouteDecision(path="tool", skip_rag=False, skip_tools=False, forced_tool_name=tool_name)

    content = brain_message.content.strip().casefold()
    if _needs_tooling(content):
        return RouteDecision(path="tool", skip_rag=False, skip_tools=False)
    return RouteDecision(path="direct", skip_rag=True, skip_tools=True)


def _needs_tooling(content: str) -> bool:
    if not content:
        return False
    if _contains_any(content, _TOOL_MEMORY_HINTS_CASEFOLDED):
        return True
    if _contains_any(content, _TOOL_ACTION_HINTS_CASEFOLDED):
        return True
    has_query_verb = _contains_any(content, _TOOL_QUERY_VERBS_CASEFOLDED)
    has_query_target = _contains_any(content, _TOOL_QUERY_TARGETS_CASEFOLDED)
    return has_query_verb and has_query_target


def _contains_any(content: str, hints: tuple[str, ...]) -> bool:
    return any(hint in content for hint in hints)


def _is_forced_tool_call(brain_message: BrainMessage) -> bool:
    original_user_message = brain_message.metadata.get(METADATA_ORIGINAL_USER_MESSAGE)
    return bool(original_user_message) and brain_message.content.startswith(_SLASH_TOOL_REWRITE_PREFIX)


def _extract_forced_tool_name(content: str) -> str | None:
    """Extract the tool name from a slash-command-rewritten message."""
    if not content.startswith(_SLASH_TOOL_REWRITE_PREFIX):
        return None
    rest = content[len(_SLASH_TOOL_REWRITE_PREFIX):]
    end = rest.find("`")
    return rest[:end] or None if end >= 0 else None


def enforce_context_budget(
    messages: list[dict[str, Any]],
    *,
    total_char_budget: int,
) -> list[dict[str, Any]]:
    """Trim messages to fit within budget.

    Strategy order:
    1. Drop oldest history turns (keep system + last user)
    2. Compress system prompt (head+tail truncation)
    """
    if _total_chars(messages) <= total_char_budget:
        return list(messages)

    trimmed = _trim_history(messages, total_char_budget)
    if _total_chars(trimmed) <= total_char_budget:
        return trimmed

    return _compress_system(trimmed, total_char_budget)


def _total_chars(messages: list[dict[str, Any]]) -> int:
    return sum(_message_chars(message) for message in messages)


def _message_chars(message: dict[str, Any]) -> int:
    return len(str(message.get("content", "")))


def _trim_history(
    messages: list[dict[str, Any]],
    budget: int,
) -> list[dict[str, Any]]:
    """Drop oldest conversation turns between system and the last user message."""
    if len(messages) <= 2:
        return list(messages)

    system = messages[0] if messages[0].get("role") == "system" else None
    last_user = messages[-1]
    history = messages[1:-1] if system else messages[:-1]

    kept: list[dict[str, Any]] = []
    base_cost = _message_chars(last_user)
    if system:
        base_cost += _message_chars(system)

    remaining = budget - base_cost
    for msg in reversed(history):
        cost = _message_chars(msg)
        if remaining - cost < 0:
            break
        kept.append(msg)
        remaining -= cost

    kept.reverse()
    result: list[dict[str, Any]] = []
    if system:
        result.append(system)
    result.extend(kept)
    result.append(last_user)
    return result


def _compress_system(
    messages: list[dict[str, Any]],
    budget: int,
) -> list[dict[str, Any]]:
    """Compress the system prompt to fit remaining budget."""
    if not messages or messages[0].get("role") != "system":
        return list(messages)

    non_system_cost = sum(_message_chars(message) for message in messages[1:])
    system_budget = max(budget - non_system_cost, 0)
    compressed_content = compress_text(
        str(messages[0].get("content", "")),
        system_budget,
    )

    return [
        {**messages[0], "content": compressed_content},
        *messages[1:],
    ]

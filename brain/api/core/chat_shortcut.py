"""Short-circuit chat handlers for slash commands that produce a fixed UI action.

Some slash commands (e.g. ``/graphify``) should render an embedded widget
immediately without round-tripping through the LLM. This module turns such
commands into a synthetic ``request_action`` tool step and a short assistant
reply, which the SSE streamer can emit directly.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from tools.actions import build_action_request


@dataclass(slots=True, frozen=True)
class ShortcutToolStep:
    """Fields for the synthetic ToolEvent that the SSE route emits."""
    tool_call_id: str
    name: str
    arguments: str
    result: str


@dataclass(slots=True, frozen=True)
class ChatShortcut:
    """A precomputed chat turn that bypasses the LLM."""

    reply: str
    tool_step: ShortcutToolStep


def try_shortcut(message: str) -> ChatShortcut | None:
    """If ``message`` is a supported shortcut slash command, return a precomputed turn."""
    stripped = message.strip()
    if not stripped.startswith("/"):
        return None

    command, _, rest = stripped[1:].partition(" ")
    command = command.strip().casefold()
    rest = rest.strip()

    if command == "graphify":
        return _graphify_shortcut(rest)
    return None


def _graphify_shortcut(query: str) -> ChatShortcut:
    reason = f"查詢：{query}" if query else None
    payload = build_action_request(
        action="embed_graph_view",
        params={"query": query} if query else {},
        reason=reason,
    )
    reply = "已在下方嵌入知識圖譜。" if not query else f"已在下方嵌入知識圖譜（查詢：{query}）。"
    tool_step = ShortcutToolStep(
        tool_call_id=f"shortcut-{uuid.uuid4().hex[:8]}",
        name="request_action",
        arguments=json.dumps({"action": "embed_graph_view"}, ensure_ascii=False),
        result=json.dumps(payload, ensure_ascii=False),
    )
    return ChatShortcut(reply=reply, tool_step=tool_step)

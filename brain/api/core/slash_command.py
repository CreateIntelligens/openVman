"""Slash command resolver — rewrites /command messages into LLM-friendly instructions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from safety.observability import log_event


_SLASH_RE = re.compile(r"^/(\w+)\s*(.*)", re.DOTALL)


@dataclass(slots=True)
class SlashRewrite:
    """A rewritten user message that instructs the LLM to call a specific tool."""
    rewritten: str
    skill_id: str
    tool_name: str


def try_rewrite_slash(
    message: str,
    skill_manager: Any,
) -> SlashRewrite | None:
    """If message starts with /skill_id, rewrite it to instruct the LLM to call the tool.

    Returns None if the message is not a slash command or the skill doesn't exist.
    """
    m = _SLASH_RE.match(message.strip())
    if m is None:
        return None

    command = m.group(1)
    args_text = m.group(2).strip()

    # /skill_id:tool_name or /skill_id
    skill_id, _, tool_suffix = command.partition(":")

    skill = skill_manager.get_skill(skill_id)
    if skill is None or not skill.enabled:
        return None

    if tool_suffix:
        tool_name = tool_suffix
    elif skill.manifest.tools:
        tool_name = skill.manifest.tools[0].name
    else:
        return None

    # Check handler exists
    if tool_name not in skill.handlers:
        return None

    namespaced = f"{skill_id}:{tool_name}"

    # Build the rewritten message
    if args_text:
        rewritten = f"[系統指令] 請立即呼叫工具 `{namespaced}`，使用者的輸入為：{args_text}"
    else:
        rewritten = f"[系統指令] 請立即呼叫工具 `{namespaced}`，不需要額外參數。"

    log_event("slash_command_rewrite", skill_id=skill_id, tool_name=tool_name, has_args=bool(args_text))
    return SlashRewrite(rewritten=rewritten, skill_id=skill_id, tool_name=tool_name)

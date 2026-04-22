"""Slash command resolver — rewrites /command messages into LLM-friendly instructions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from safety.observability import log_event, log_exception
from tools.skill import SkillRef


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
    *,
    project_id: str | None = None,
) -> SlashRewrite | None:
    """If message starts with /skill_id, rewrite it to instruct the LLM to call the tool.

    Resolution order when ``project_id`` is given: project skill first, then
    shared. This matches the convention elsewhere in the manager.
    """
    m = _SLASH_RE.match(message.strip())
    if m is None:
        return None

    command = m.group(1)
    args_text = m.group(2).strip()

    skill_id, _, tool_suffix = command.partition(":")

    if project_id and hasattr(skill_manager, "reload_project_skills"):
        try:
            skill_manager.reload_project_skills(project_id)
        except Exception as exc:  # noqa: BLE001 — slash rewrite should be resilient
            log_exception("slash_reload_project_skills_failed", exc, project_id=project_id)

    skill = skill_manager.get_skill(SkillRef(skill_id=skill_id, project_id=project_id))
    if skill is None or not skill.enabled:
        return None

    if tool_suffix:
        tool_name = tool_suffix
    elif skill.manifest.tools:
        tool_name = skill.manifest.tools[0].name
    else:
        return None

    if tool_name not in skill.handlers:
        return None

    namespaced = f"{skill.tool_prefix}{tool_name}"

    if args_text:
        rewritten = f"[系統指令] 請立即呼叫工具 `{namespaced}`，使用者的輸入為：{args_text}"
    else:
        rewritten = f"[系統指令] 請立即呼叫工具 `{namespaced}`，不需要額外參數。"

    log_event(
        "slash_command_rewrite",
        skill_id=skill_id,
        tool_name=tool_name,
        scope=skill.scope,
        project_id=skill.project_id,
        has_args=bool(args_text),
    )
    return SlashRewrite(rewritten=rewritten, skill_id=skill_id, tool_name=tool_name)

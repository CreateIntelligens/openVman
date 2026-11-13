"""Built-in tool registry for the Brain agent loop."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING, Any

from safety.observability import log_exception
from tools.context import (
    active_persona_id,
    active_project_id,
    active_reply_mode,
    active_user_message,
)

logger = logging.getLogger("brain.tools")

if TYPE_CHECKING:
    from .skill import Skill

ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def register_skill_tools(self, skill: Skill) -> None:
        """Register all tools provided by a skill, with namespacing."""
        scope_label = (
            f"[{skill.manifest.name} · project:{skill.project_id}]"
            if skill.scope == "project"
            else f"[{skill.manifest.name}]"
        )
        for tool_def in skill.manifest.tools:
            handler = skill.handlers.get(tool_def.name)
            if not handler:
                continue
            self.register(Tool(
                name=f"{skill.tool_prefix}{tool_def.name}",
                description=f"{scope_label} {tool_def.description}",
                parameters=tool_def.parameters,
                handler=handler,
            ))

    def unregister_skill_tools(self, skill: Skill) -> None:
        """Remove all tools registered by a skill."""
        prefix = skill.tool_prefix
        for name in [n for n in self._tools if n.startswith(prefix)]:
            del self._tools[name]

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ValueError(f"未知工具：{name}")
        return self._tools[name]

    def list_tools(self) -> list[Tool]:
        return sorted(self._tools.values(), key=lambda t: t.name)

    def build_openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self.list_tools()
        ]


_registry_lock = RLock()
_registry: ToolRegistry | None = None
_last_synced_project: str | None = None
_sync_invalidated: bool = True
_last_skill_revision: int | None = None


def activate_project_sync(project_id: str) -> ToolRegistry:
    """Set the active project context and return a synced registry."""
    token = active_project_id.set(project_id or "default")
    try:
        return get_tool_registry()
    finally:
        active_project_id.reset(token)


def invalidate_skill_tools_sync() -> None:
    """Force the next ``get_tool_registry()`` call to re-sync skill tools."""
    global _sync_invalidated
    _sync_invalidated = True


def _sync_skill_tools(registry: ToolRegistry, manager: Any) -> None:
    active_project = active_project_id.get()
    if hasattr(manager, "reload_project_skills"):
        try:
            manager.reload_project_skills(active_project)
        except Exception as exc:  # noqa: BLE001
            log_exception("skill_project_reload_failed", exc, project_id=active_project)

    visible = [
        skill
        for skill in manager.list_skills()
        if skill.scope == "shared" or skill.project_id == active_project
    ]
    enabled_names = {
        f"{skill.tool_prefix}{tool.name}"
        for skill in visible if skill.enabled
        for tool in skill.manifest.tools if tool.name in skill.handlers
    }

    stale = [
        name
        for name in registry._tools
        if ":" in name
        and name not in enabled_names
    ]
    for name in stale:
        del registry._tools[name]

    for skill in visible:
        if skill.enabled:
            registry.register_skill_tools(skill)


def get_tool_registry() -> ToolRegistry:
    # A request keeps its own tools even when another thread selects a project.
    with _registry_lock:
        return _get_tool_registry_snapshot()


def _get_tool_registry_snapshot() -> ToolRegistry:
    """Return the global tool registry, ensuring built-in and skill tools are synced."""
    global _registry, _last_synced_project, _sync_invalidated, _last_skill_revision

    # 1. Initialize core registry and built-in tools if first call
    if _registry is None:
        from tools.builtin import list_builtin_tools
        _registry = ToolRegistry()
        for tool in list_builtin_tools():
            _registry.register(tool)

    # Admin changes are discovered from shared files by every worker.
    active_project = active_project_id.get()
    try:
        from .skill_manager import get_skill_manager

        manager = get_skill_manager()
        with getattr(manager, "_lock", nullcontext()):
            manager.reload_project_skills(active_project)
            revision = manager.revision
            if (
                _sync_invalidated
                or active_project != _last_synced_project
                or revision != _last_skill_revision
            ):
                _sync_skill_tools(_registry, manager)
                _last_synced_project = active_project
                _last_skill_revision = revision
                _sync_invalidated = False
    except Exception as exc:
        log_exception("skill_registry_sync_failed", exc, project_id=active_project)

    snapshot = ToolRegistry()
    project_prefix = f"proj:{active_project}:"
    snapshot._tools = {
        name: tool for name, tool in _registry._tools.items()
        if not name.startswith("proj:") or name.startswith(project_prefix)
    }
    return snapshot


@contextmanager
def bind_tool_context(
    persona_id: str,
    project_id: str = "default",
    *,
    user_message: str = "",
    reply_mode: str = "",
):
    """Bind persona / project / user-message / mode context for tool execution."""
    persona_token = active_persona_id.set(persona_id or "default")
    project_token = active_project_id.set(project_id or "default")
    user_token = active_user_message.set(user_message or "")
    mode_token = active_reply_mode.set(reply_mode or "")
    try:
        yield
    finally:
        active_persona_id.reset(persona_token)
        active_project_id.reset(project_token)
        active_user_message.reset(user_token)
        active_reply_mode.reset(mode_token)

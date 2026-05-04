"""Built-in tool registry for the Brain agent loop."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from safety.observability import log_exception
from tools.context import active_persona_id, active_project_id, active_user_message


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


_registry: ToolRegistry | None = None
_last_synced_project: str | None = None
_sync_invalidated: bool = True


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
    enabled_prefixes = {skill.tool_prefix for skill in visible if skill.enabled}

    stale = [
        name
        for name in registry._tools
        if ":" in name
        and not any(name.startswith(prefix) for prefix in enabled_prefixes)
    ]
    for name in stale:
        del registry._tools[name]

    for skill in visible:
        if skill.enabled:
            registry.register_skill_tools(skill)


def get_tool_registry() -> ToolRegistry:
    """Return the global tool registry, ensuring built-in and skill tools are synced."""
    global _registry, _last_synced_project, _sync_invalidated

    # 1. Initialize core registry and built-in tools if first call
    if _registry is None:
        from tools.builtin import list_builtin_tools
        _registry = ToolRegistry()
        for tool in list_builtin_tools():
            _registry.register(tool)

    # 2. Check if re-sync of skill tools is needed
    active_project = active_project_id.get()
    if _sync_invalidated or active_project != _last_synced_project:
        try:
            from .skill_manager import get_skill_manager
            _sync_skill_tools(_registry, get_skill_manager())
            _last_synced_project = active_project
            _sync_invalidated = False
        except Exception as exc:
            log_exception("skill_registry_sync_failed", exc, project_id=active_project)

    return _registry



@contextmanager
def bind_tool_context(
    persona_id: str,
    project_id: str = "default",
    *,
    user_message: str = "",
):
    """Bind persona / project / user-message context for tool execution."""
    persona_token = active_persona_id.set(persona_id or "default")
    project_token = active_project_id.set(project_id or "default")
    user_token = active_user_message.set(user_message or "")
    try:
        yield
    finally:
        active_persona_id.reset(persona_token)
        active_project_id.reset(project_token)
        active_user_message.reset(user_token)

"""Skill and SkillManifest models for modular brain capabilities."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

SkillScope = Literal["shared", "project"]

# 技能 ID 會變成目錄名稱與 Python 函式名稱（``<id>_action``），只收合法識別字，
# 不能帶路徑字元。Backend 的 ``app.skill_write_guard.SKILL_ID_PATTERN`` 與此相同。
SKILL_ID_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
_SKILL_ID_RE = re.compile(SKILL_ID_PATTERN)


def is_valid_skill_id(skill_id: str) -> bool:
    return bool(_SKILL_ID_RE.fullmatch(skill_id))


@dataclass(frozen=True, slots=True)
class SkillRef:
    """Value object identifying a skill within a scope."""
    skill_id: str
    scope: SkillScope | None = None
    project_id: str | None = None

    def resolve_key(self) -> str:
        """Lookup key used by SkillManager. Project scope wins when no explicit scope + project_id."""
        if self.scope == "project" or (self.scope is None and self.project_id):
            return f"project:{self.project_id}:{self.skill_id}"
        return f"shared:{self.skill_id}"


@dataclass(frozen=True, slots=True)
class SkillToolDefinition:
    """Definition of a tool provided by a skill."""
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SkillManifest:
    """Metadata for a skill package."""
    id: str
    name: str
    description: str
    version: str = "0.1.0"
    tools: list[SkillToolDefinition] = field(default_factory=list)
    config_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class Skill:
    """A loaded skill instance.

    scope:
      - "shared": from the global skills dir, available to all projects.
      - "project": scoped to a specific project_id (same id may exist in
        multiple projects; shared + project with same id may coexist).
    """
    manifest: SkillManifest
    path: str
    scope: SkillScope = "shared"
    project_id: str | None = None
    handlers: dict[str, Callable[[dict[str, Any]], Any]] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    warnings: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Unique key across scopes: 'shared:<id>' or 'project:<pid>:<id>'."""
        if self.scope == "project":
            return f"project:{self.project_id}:{self.manifest.id}"
        return f"shared:{self.manifest.id}"

    @property
    def tool_prefix(self) -> str:
        """Namespace prefix for this skill's registered tools.

        Shared skills keep the legacy `<id>:` form for backwards compat.
        Project skills use `proj:<pid>:<id>:` to coexist without collision.
        """
        if self.scope == "project":
            return f"proj:{self.project_id}:{self.manifest.id}:"
        return f"{self.manifest.id}:"

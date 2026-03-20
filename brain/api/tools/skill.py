"""Skill and SkillManifest models for modular brain capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


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
    """A loaded skill instance."""
    manifest: SkillManifest
    path: str
    handlers: dict[str, Callable[[dict[str, Any]], Any]] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

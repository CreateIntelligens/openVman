"""Skill and SkillManifest models for modular brain capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True, slots=True)
class SkillToolDefinition:
    """Definition of a tool provided by a skill."""
    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass(frozen=True, slots=True)
class SkillManifest:
    """Metadata for a skill package."""
    id: str
    name: str
    description: str
    version: str = "0.1.0"
    tools: List[SkillToolDefinition] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Skill:
    """A loaded skill instance."""
    manifest: SkillManifest
    path: str
    handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

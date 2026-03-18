"""Skill manager for discovering, loading, and managing brain skills."""

from __future__ import annotations

import importlib.util
import os
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

from safety.observability import log_event, log_exception
from .skill import Skill, SkillManifest, SkillToolDefinition


class SkillManager:
    """Manages the lifecycle of brain skills."""

    def __init__(self, skills_dir: str):
        self.skills_dir = Path(skills_dir)
        self.skills: Dict[str, Skill] = {}

    def scan_and_load_skills(self) -> None:
        """Scan the skills directory and load all valid skills."""
        if not self.skills_dir.exists():
            log_event("skills_dir_missing", path=str(self.skills_dir))
            return

        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                try:
                    self._load_skill(skill_dir)
                except Exception as exc:
                    log_exception("skill_load_failed", exc, skill_dir=skill_dir.name)

    def _load_skill(self, skill_dir: Path) -> None:
        """Load a single skill from its directory."""
        manifest_path = skill_dir / "skill.yaml"
        if not manifest_path.exists():
            return

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = yaml.safe_load(f)

        # Basic validation (could be more robust with pydantic/jsonschema)
        skill_id = manifest_data.get("id")
        if not skill_id:
            raise ValueError(f"Skill manifest missing 'id': {manifest_path}")

        tools_data = manifest_data.get("tools", [])
        tools = [
            SkillToolDefinition(
                name=t["name"],
                description=t["description"],
                parameters=t["parameters"]
            )
            for t in tools_data
        ]

        manifest = SkillManifest(
            id=skill_id,
            name=manifest_data.get("name", skill_id),
            description=manifest_data.get("description", ""),
            version=manifest_data.get("version", "0.1.0"),
            tools=tools,
            config_schema=manifest_data.get("config_schema", {})
        )

        skill = Skill(manifest=manifest, path=str(skill_dir))
        
        # Load implementation module if main.py exists
        main_py = skill_dir / "main.py"
        if main_py.exists():
            self._bind_handlers(skill, main_py)

        self.skills[skill_id] = skill
        log_event("skill_loaded", skill_id=skill_id, tools_count=len(tools))

    def _bind_handlers(self, skill: Skill, main_py: Path) -> None:
        """Dynamically load handlers from the skill's main.py."""
        module_name = f"brain.skills.{skill.manifest.id}"
        spec = importlib.util.spec_from_file_location(module_name, str(main_py))
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Map manifest tool names to module functions
            for tool_def in skill.manifest.tools:
                handler = getattr(module, tool_def.name, None)
                if handler and callable(handler):
                    skill.handlers[tool_def.name] = handler
                else:
                    log_event("skill_handler_missing", skill_id=skill.manifest.id, tool_name=tool_def.name)

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Retrieve a loaded skill by ID."""
        return self.skills.get(skill_id)

    def list_skills(self) -> List[Skill]:
        """List all loaded skills."""
        return list(self.skills.values())


_instance: SkillManager | None = None

def get_skill_manager() -> SkillManager:
    """Singleton accessor for SkillManager."""
    global _instance
    if _instance is None:
        # Default skills dir relative to project root or via env
        from config import get_settings
        skills_path = os.environ.get("BRAIN_SKILLS_DIR", os.path.join(os.getcwd(), "brain/skills"))
        _instance = SkillManager(skills_path)
    return _instance

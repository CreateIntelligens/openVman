"""Skill manager for discovering, loading, and managing brain skills."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from safety.observability import log_event, log_exception

from .skill import Skill, SkillManifest, SkillToolDefinition

if TYPE_CHECKING:
    from .tool_registry import ToolRegistry

ALLOWED_SKILL_FILES = frozenset({"skill.yaml", "main.py"})

_SKILL_YAML_TEMPLATE = """\
id: {skill_id}
name: {name}
description: {description}
version: "0.1.0"
tools:
  - name: {skill_id}_action
    description: "{name} action"
    parameters:
      type: object
      properties:
        query:
          type: string
          description: "Input query"
      required:
        - query
"""

_MAIN_PY_TEMPLATE = '''\
"""Skill: {name}"""


def {skill_id}_action(args: dict) -> dict:
    """TODO: implement {name} logic."""
    query = args.get("query", "")
    return {{"result": f"echo: {{query}}"}}
'''


class SkillManager:
    """Manages the lifecycle of brain skills."""

    def __init__(self, skills_dir: str):
        self.skills_dir = Path(skills_dir)
        self.skills: dict[str, Skill] = {}

    # ------------------------------------------------------------------
    # Discovery & Loading
    # ------------------------------------------------------------------

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
        # Remove stale module so reimport works on reload
        sys.modules.pop(module_name, None)
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
                    available_fns = [
                        n for n, obj in vars(module).items()
                        if callable(obj) and not n.startswith("_")
                    ]
                    hint = ""
                    if available_fns:
                        hint = f"（main.py 可用函式：{', '.join(available_fns)}）"
                    warning = (
                        f"tool '{tool_def.name}' 在 main.py 中找不到對應函式，"
                        f"該工具將無法使用。{hint}"
                    )
                    skill.warnings.append(warning)
                    log_event("skill_handler_missing", skill_id=skill.manifest.id, tool_name=tool_def.name)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def _require_skill(self, skill_id: str) -> Skill:
        """Return a loaded skill or raise ValueError."""
        skill = self.skills.get(skill_id)
        if skill is None:
            raise ValueError(f"Skill not found: {skill_id}")
        return skill

    def get_skill(self, skill_id: str) -> Skill | None:
        """Retrieve a loaded skill by ID."""
        return self.skills.get(skill_id)

    def list_skills(self) -> list[Skill]:
        """List all loaded skills."""
        return list(self.skills.values())

    # ------------------------------------------------------------------
    # Enable / Disable
    # ------------------------------------------------------------------

    def toggle_skill(self, skill_id: str, registry: ToolRegistry) -> Skill:
        """Toggle a skill between enabled and disabled."""
        skill = self._require_skill(skill_id)
        if skill.enabled:
            return self.disable_skill(skill_id, registry)
        return self.enable_skill(skill_id, registry)

    def enable_skill(self, skill_id: str, registry: ToolRegistry) -> Skill:
        skill = self._require_skill(skill_id)
        skill.enabled = True
        registry.register_skill_tools(skill)
        log_event("skill_enabled", skill_id=skill_id)
        return skill

    def disable_skill(self, skill_id: str, registry: ToolRegistry) -> Skill:
        skill = self._require_skill(skill_id)
        skill.enabled = False
        registry.unregister_skill_tools(skill)
        log_event("skill_disabled", skill_id=skill_id)
        return skill

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_skill(self, skill_id: str, name: str, description: str, registry: ToolRegistry) -> Skill:
        """Create a new skill directory with skeleton files, load and register it."""
        if skill_id in self.skills:
            raise ValueError(f"Skill already exists: {skill_id}")

        skill_dir = self.skills_dir / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)

        yaml_content = _SKILL_YAML_TEMPLATE.format(skill_id=skill_id, name=name, description=description)
        (skill_dir / "skill.yaml").write_text(yaml_content, encoding="utf-8")

        py_content = _MAIN_PY_TEMPLATE.format(skill_id=skill_id, name=name)
        (skill_dir / "main.py").write_text(py_content, encoding="utf-8")

        self._load_skill(skill_dir)
        skill = self._require_skill(skill_id)
        registry.register_skill_tools(skill)
        log_event("skill_created", skill_id=skill_id)
        return skill

    def delete_skill(self, skill_id: str, registry: ToolRegistry) -> None:
        """Unregister, remove from memory, and delete the skill directory."""
        skill = self._require_skill(skill_id)
        registry.unregister_skill_tools(skill)
        shutil.rmtree(skill.path, ignore_errors=True)
        del self.skills[skill_id]
        log_event("skill_deleted", skill_id=skill_id)

    # ------------------------------------------------------------------
    # File read / write
    # ------------------------------------------------------------------

    def get_skill_files(self, skill_id: str) -> dict[str, str]:
        """Read the raw contents of skill.yaml and main.py."""
        skill = self._require_skill(skill_id)
        skill_dir = Path(skill.path)
        files: dict[str, str] = {}
        for fname in ("skill.yaml", "main.py"):
            fpath = skill_dir / fname
            if fpath.exists():
                files[fname] = fpath.read_text(encoding="utf-8")
        return files

    def update_skill_files(self, skill_id: str, files: dict[str, str], registry: ToolRegistry) -> Skill:
        """Write updated files to disk and hot-reload the skill."""
        skill = self._require_skill(skill_id)
        skill_dir = Path(skill.path)
        for fname, content in files.items():
            if fname not in ALLOWED_SKILL_FILES:
                raise ValueError(f"Cannot update file: {fname}")
            (skill_dir / fname).write_text(content, encoding="utf-8")

        return self._reload_single(skill_id, registry)

    # ------------------------------------------------------------------
    # Reload
    # ------------------------------------------------------------------

    def _reload_single(self, skill_id: str, registry: ToolRegistry) -> Skill:
        """Unregister old tools, re-load from disk, register if enabled."""
        old_skill = self.skills.get(skill_id)
        was_enabled = old_skill.enabled if old_skill else True
        if old_skill:
            registry.unregister_skill_tools(old_skill)

        skill_dir = self.skills_dir / skill_id
        if skill_dir.exists():
            self._load_skill(skill_dir)

        skill = self._require_skill(skill_id)
        skill.enabled = was_enabled
        if skill.enabled:
            registry.register_skill_tools(skill)
        log_event("skill_reloaded", skill_id=skill_id)
        return skill

    def reload_all(self, registry: ToolRegistry) -> list[Skill]:
        """Unregister all skill tools, rescan directory, register enabled skills."""
        # Unregister all existing skill tools
        for skill in self.skills.values():
            registry.unregister_skill_tools(skill)

        self.skills.clear()
        self.scan_and_load_skills()

        # Register tools for enabled skills
        for skill in self.skills.values():
            if skill.enabled:
                registry.register_skill_tools(skill)

        log_event("skills_reloaded_all", count=len(self.skills))
        return list(self.skills.values())


_instance: SkillManager | None = None

def get_skill_manager() -> SkillManager:
    """Singleton accessor for SkillManager."""
    global _instance
    if _instance is None:
        skills_path = os.environ.get("BRAIN_SKILLS_DIR", "/skills")
        _instance = SkillManager(skills_path)
    return _instance

"""Skill manager for discovering, loading, and managing brain skills.

Skills live in two scopes:
  * **shared** — ``brain/skills/`` (mounted at ``/skills`` in container).
    Available to every project.
  * **project** — ``brain/data/projects/<project_id>/skills/``. Scoped to a
    single project. May share an id with a shared skill; both coexist and
    register under separate tool namespaces (see ``Skill.tool_prefix``).

Project skills are loaded lazily: on first access or on explicit
``reload_project_skills(pid)``. The manager keeps at most one project's
skills loaded at a time (the ``_active_project_id``) to avoid unbounded
memory use with many projects.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any

import yaml
from infra.file_lock import atomic_write_text, file_lock
from safety.observability import log_event, log_exception

from .skill import (
    Skill,
    SkillManifest,
    SkillRef,
    SkillScope,
    SkillToolDefinition,
)

if TYPE_CHECKING:
    from .tool_registry import ToolRegistry

SKILL_FILE_NAMES = ("skill.yaml", "main.py")
ALLOWED_SKILL_FILES = frozenset(SKILL_FILE_NAMES)

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


def _synchronized(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return guarded


class SkillManager:
    """Manages the lifecycle of brain skills across shared + project scopes."""

    def __init__(self, shared_dir: str, project_root: str | None = None):
        self._lock = RLock()
        self.shared_dir = Path(shared_dir)
        self.project_root = Path(project_root) if project_root else None
        # Shared skill packages are mounted read-only; mutable state belongs in /data.
        self.state_root = (
            self.project_root.parent if self.project_root else self.shared_dir.parent
        ) / "skill_states"
        self.skills: dict[str, Skill] = {}
        self._loaded_project: str | None = None
        self._signature: tuple = ()
        self.revision = 0

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def _state_path(self, skill_dir: Path) -> Path:
        key = hashlib.sha256(str(skill_dir.resolve()).encode("utf-8")).hexdigest()
        return self.state_root / f"{key}.json"

    def _project_skills_dir(self, project_id: str) -> Path | None:
        if not self.project_root:
            return None
        return self.project_root / project_id / "skills"

    def _target_dir(self, scope: SkillScope, project_id: str | None) -> Path | None:
        if scope == "shared":
            return self.shared_dir
        return self._project_skills_dir(project_id or "")

    def _resolve_skill_dir(
        self,
        skill_id: str,
        old_skill: Skill | None,
        *,
        scope: SkillScope,
        project_id: str | None,
    ) -> Path | None:
        if old_skill is not None:
            return Path(old_skill.path)

        target_dir = self._target_dir(scope, project_id)
        if target_dir is None:
            return None
        return target_dir / skill_id

    # ------------------------------------------------------------------
    # Discovery & Loading
    # ------------------------------------------------------------------

    @_synchronized
    def scan_and_load_skills(self) -> None:
        """Load shared skills (always) and the active project's skills if any."""
        self._scan_dir(self.shared_dir, scope="shared", project_id=None)
        self._signature = self._disk_signature()
        self.revision += 1

    def _disk_signature(self) -> tuple:
        directories = [self.shared_dir]
        if self._loaded_project:
            project_dir = self._project_skills_dir(self._loaded_project)
            if project_dir is not None:
                directories.append(project_dir)
        signature = []
        for directory in directories:
            try:
                children = sorted(directory.iterdir())
            except FileNotFoundError:
                signature.append((str(directory), None))
                continue
            for child in children:
                if not child.is_dir():
                    continue
                paths = [child / name for name in SKILL_FILE_NAMES]
                paths.append(self._state_path(child))
                for path in paths:
                    try:
                        stat = path.stat()
                        signature.append((str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino))
                    except FileNotFoundError:
                        signature.append((str(path), None))
        return tuple(signature)

    @_synchronized
    def refresh_if_changed(self) -> None:
        """Notice changes made by the admin process without an HTTP refresh fanout."""
        signature = self._disk_signature()
        if signature == self._signature:
            return
        self.skills.clear()
        self._scan_dir(self.shared_dir, scope="shared", project_id=None)
        if self._loaded_project:
            project_dir = self._project_skills_dir(self._loaded_project)
            if project_dir is not None:
                self._scan_dir(project_dir, scope="project", project_id=self._loaded_project)
        self._signature = signature
        self.revision += 1

    def _scan_dir(self, skills_dir: Path, *, scope: SkillScope, project_id: str | None) -> None:
        if not skills_dir.exists():
            return
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir():
                try:
                    self._load_skill(skill_dir, scope=scope, project_id=project_id)
                except Exception as exc:
                    log_exception(
                        "skill_load_failed",
                        exc,
                        skill_dir=skill_dir.name,
                        scope=scope,
                        project_id=project_id,
                    )

    @_synchronized
    def reload_project_skills(self, project_id: str) -> None:
        """Unload previously active project's skills and load ``project_id``'s."""
        self.refresh_if_changed()
        if self._loaded_project == project_id:
            return
        self._unload_project_skills()
        self._loaded_project = project_id
        proj_dir = self._project_skills_dir(project_id)
        if proj_dir is not None:
            self._scan_dir(proj_dir, scope="project", project_id=project_id)
        self._signature = self._disk_signature()
        self.revision += 1

    def _unload_project_skills(self) -> None:
        project_keys = [key for key, skill in self.skills.items() if skill.scope == "project"]
        for key in project_keys:
            del self.skills[key]

    def _build_tool_definitions(self, tools_data: list[dict[str, Any]]) -> list[SkillToolDefinition]:
        return [
            SkillToolDefinition(
                name=str(tool_data["name"]),
                description=str(tool_data["description"]),
                parameters=dict(tool_data["parameters"]),
            )
            for tool_data in tools_data
        ]

    def _read_manifest(self, manifest_path: Path) -> SkillManifest:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = yaml.safe_load(f)

        skill_id = manifest_data.get("id")
        if not skill_id:
            raise ValueError(f"Skill manifest missing 'id': {manifest_path}")

        return SkillManifest(
            id=skill_id,
            name=manifest_data.get("name", skill_id),
            description=manifest_data.get("description", ""),
            version=manifest_data.get("version", "0.1.0"),
            tools=self._build_tool_definitions(manifest_data.get("tools", [])),
            config_schema=manifest_data.get("config_schema", {}),
        )

    def _load_skill(
        self,
        skill_dir: Path,
        *,
        scope: SkillScope = "shared",
        project_id: str | None = None,
    ) -> None:
        """Load a single skill from its directory."""
        manifest_path = skill_dir / "skill.yaml"
        if not manifest_path.exists():
            return

        manifest = self._read_manifest(manifest_path)

        skill = Skill(
            manifest=manifest,
            path=str(skill_dir),
            scope=scope,
            project_id=project_id,
        )
        state_path = self._state_path(skill_dir)
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or not isinstance(state.get("enabled"), bool):
                raise ValueError(f"Invalid skill state: {state_path}")
            skill.enabled = state["enabled"]

        main_py = skill_dir / "main.py"
        if main_py.exists():
            self._bind_handlers(skill, main_py)

        self.skills[skill.key] = skill
        log_event(
            "skill_loaded",
            skill_id=manifest.id,
            scope=scope,
            project_id=project_id,
            tools_count=len(manifest.tools),
        )

    def _bind_handlers(self, skill: Skill, main_py: Path) -> None:
        """Dynamically load handlers from the skill's main.py."""
        module_name = self._module_name(skill)
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, str(main_py))
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            # Reload same-sized edits immediately instead of accepting timestamp-based pyc.
            exec(  # noqa: S102 - Skill Python is an existing operator-managed extension.
                compile(main_py.read_bytes(), str(main_py), "exec"), module.__dict__,
            )

            for tool_def in skill.manifest.tools:
                handler = getattr(module, tool_def.name, None)
                if handler and callable(handler):
                    skill.handlers[tool_def.name] = handler
                else:
                    self._record_missing_handler(skill, module, tool_def.name)

    def _module_name(self, skill: Skill) -> str:
        if skill.scope == "project":
            return f"brain.skills.project.{skill.project_id}.{skill.manifest.id}"
        return f"brain.skills.{skill.manifest.id}"

    def _record_missing_handler(self, skill: Skill, module: object, tool_name: str) -> None:
        available_fns = [
            name for name, obj in vars(module).items()
            if callable(obj) and not name.startswith("_")
        ]
        hint = ""
        if available_fns:
            hint = f"（main.py 可用函式：{', '.join(available_fns)}）"
        warning = (
            f"tool '{tool_name}' 在 main.py 中找不到對應函式，"
            f"該工具將無法使用。{hint}"
        )
        skill.warnings.append(warning)
        log_event(
            "skill_handler_missing",
            skill_id=skill.manifest.id,
            scope=skill.scope,
            project_id=skill.project_id,
            tool_name=tool_name,
        )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    @_synchronized
    def _require_skill(self, ref: SkillRef) -> Skill:
        """Return a loaded skill or raise ValueError.

        When no explicit scope is given, project scope takes precedence over shared.
        """
        if ref.project_id and ref.scope != "shared":
            self.reload_project_skills(ref.project_id)
        else:
            self.refresh_if_changed()
        if ref.scope:
            key = ref.resolve_key()
            skill = self.skills.get(key)
            if skill is None:
                raise ValueError(f"Skill not found: {ref.skill_id} (scope={ref.scope})")
            return skill
        if ref.project_id:
            proj = self.skills.get(f"project:{ref.project_id}:{ref.skill_id}")
            if proj is not None:
                return proj
        shared = self.skills.get(f"shared:{ref.skill_id}")
        if shared is None:
            raise ValueError(f"Skill not found: {ref.skill_id}")
        return shared

    @_synchronized
    def get_skill(self, ref: SkillRef) -> Skill | None:
        """Retrieve a loaded skill. Project scope takes precedence on collision."""
        try:
            return self._require_skill(ref)
        except ValueError:
            return None

    @_synchronized
    def list_skills(self, project_id: str | None = None) -> list[Skill]:
        """Snapshot shared skills and the requested project's skills under one lock."""
        if project_id is not None:
            self.reload_project_skills(project_id)
        else:
            self.refresh_if_changed()
        return list(self.skills.values())

    # ------------------------------------------------------------------
    # Enable / Disable
    # ------------------------------------------------------------------

    @_synchronized
    def toggle_skill(self, ref: SkillRef, registry: ToolRegistry) -> Skill:
        skill = self._require_skill(ref)
        return self._set_skill_enabled(skill, registry, enabled=not skill.enabled)

    @_synchronized
    def enable_skill(self, ref: SkillRef, registry: ToolRegistry) -> Skill:
        skill = self._require_skill(ref)
        return self._set_skill_enabled(skill, registry, enabled=True)

    @_synchronized
    def disable_skill(self, ref: SkillRef, registry: ToolRegistry) -> Skill:
        skill = self._require_skill(ref)
        return self._set_skill_enabled(skill, registry, enabled=False)

    def _set_skill_enabled(
        self,
        skill: Skill,
        registry: ToolRegistry,
        *,
        enabled: bool,
    ) -> Skill:
        state_path = self._state_path(Path(skill.path))
        with file_lock(state_path):
            atomic_write_text(state_path, json.dumps({"enabled": enabled}) + "\n")
        skill.enabled = enabled
        self._signature = self._disk_signature()
        self.revision += 1
        if enabled:
            registry.register_skill_tools(skill)
        else:
            registry.unregister_skill_tools(skill)
        log_event(
            "skill_enabled" if enabled else "skill_disabled",
            skill_id=skill.manifest.id,
            scope=skill.scope,
            project_id=skill.project_id,
        )
        return skill

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @_synchronized
    def create_skill(
        self,
        ref: SkillRef,
        *,
        name: str,
        description: str,
        registry: ToolRegistry,
    ) -> Skill:
        """Create a new skill in the given scope, load and register it."""
        scope: SkillScope = ref.scope or "shared"
        if scope == "project" and not ref.project_id:
            raise ValueError("project scope requires project_id")
        target_dir = self._target_dir(scope, ref.project_id)
        if target_dir is None:
            raise ValueError("No target directory available for scope")

        concrete_ref = SkillRef(skill_id=ref.skill_id, scope=scope, project_id=ref.project_id)
        if concrete_ref.resolve_key() in self.skills:
            raise ValueError(f"Skill already exists in this scope: {ref.skill_id}")

        target_dir.mkdir(parents=True, exist_ok=True)
        skill_dir = target_dir / ref.skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)

        yaml_content = _SKILL_YAML_TEMPLATE.format(skill_id=ref.skill_id, name=name, description=description)
        atomic_write_text(skill_dir / "skill.yaml", yaml_content)

        py_content = _MAIN_PY_TEMPLATE.format(skill_id=ref.skill_id, name=name)
        atomic_write_text(skill_dir / "main.py", py_content)

        self._load_skill(skill_dir, scope=scope, project_id=ref.project_id)
        self._signature = self._disk_signature()
        self.revision += 1
        skill = self._require_skill(concrete_ref)
        registry.register_skill_tools(skill)
        log_event("skill_created", skill_id=ref.skill_id, scope=scope, project_id=ref.project_id)
        return skill

    @_synchronized
    def delete_skill(self, ref: SkillRef, registry: ToolRegistry) -> None:
        skill = self._require_skill(ref)
        registry.unregister_skill_tools(skill)
        shutil.rmtree(skill.path, ignore_errors=True)
        state_path = self._state_path(Path(skill.path))
        with file_lock(state_path):
            state_path.unlink(missing_ok=True)
        del self.skills[skill.key]
        self._signature = self._disk_signature()
        self.revision += 1
        log_event("skill_deleted", skill_id=ref.skill_id, scope=skill.scope, project_id=skill.project_id)

    # ------------------------------------------------------------------
    # File read / write
    # ------------------------------------------------------------------

    @_synchronized
    def get_skill_files(self, ref: SkillRef) -> dict[str, str]:
        skill = self._require_skill(ref)
        skill_dir = Path(skill.path)
        files: dict[str, str] = {}
        for fname in SKILL_FILE_NAMES:
            try:
                files[fname] = (skill_dir / fname).read_text(encoding="utf-8")
            except FileNotFoundError:
                continue
        return files

    @_synchronized
    def update_skill_files(
        self,
        ref: SkillRef,
        files: dict[str, str],
        registry: ToolRegistry,
    ) -> Skill:
        skill = self._require_skill(ref)
        skill_dir = Path(skill.path)
        for fname, content in files.items():
            if fname not in ALLOWED_SKILL_FILES:
                raise ValueError(f"Cannot update file: {fname}")
            if fname == "main.py":
                # Skills are imported into the Brain process.  Allowing a
                # project user to replace Python source is equivalent to
                # granting arbitrary code execution in that process.
                raise ValueError("main.py is operator-managed and cannot be updated via the API")
            atomic_write_text(skill_dir / fname, content)

        return self._reload_single(
            SkillRef(skill_id=skill.manifest.id, scope=skill.scope, project_id=skill.project_id),
            registry,
        )

    # ------------------------------------------------------------------
    # Reload
    # ------------------------------------------------------------------

    def _reload_single(self, ref: SkillRef, registry: ToolRegistry) -> Skill:
        scope: SkillScope = ref.scope or "shared"
        resolved_ref = SkillRef(skill_id=ref.skill_id, scope=scope, project_id=ref.project_id)
        key = resolved_ref.resolve_key()
        old_skill = self.skills.get(key)
        if old_skill:
            registry.unregister_skill_tools(old_skill)
            del self.skills[key]

        skill_dir = self._resolve_skill_dir(ref.skill_id, old_skill, scope=scope, project_id=ref.project_id)

        if skill_dir and skill_dir.exists():
            self._load_skill(skill_dir, scope=scope, project_id=ref.project_id)

        skill = self._require_skill(resolved_ref)
        if skill.enabled:
            registry.register_skill_tools(skill)
        log_event("skill_reloaded", skill_id=ref.skill_id, scope=scope, project_id=ref.project_id)
        return skill

    @_synchronized
    def reload_all(self, registry: ToolRegistry, *, project_id: str | None = None) -> list[Skill]:
        """Re-scan shared + (optionally) a specific project's skills dir."""
        for skill in list(self.skills.values()):
            registry.unregister_skill_tools(skill)

        self.skills.clear()
        self._loaded_project = None
        self.scan_and_load_skills()
        if project_id:
            self.reload_project_skills(project_id)

        for skill in self.skills.values():
            if skill.enabled:
                registry.register_skill_tools(skill)

        log_event("skills_reloaded_all", count=len(self.skills), project_id=project_id)
        return list(self.skills.values())


_instance: SkillManager | None = None


def _default_shared_path() -> str:
    """Prefer the mounted `/skills` dir, but fall back to the repo copy in local dev."""
    mounted_path = Path("/skills")
    if mounted_path.exists():
        return str(mounted_path)
    return str(Path(__file__).resolve().parents[2] / "skills")


def _default_project_root() -> str | None:
    """Root for per-project skill dirs. Mirrors workspace layout under ``data/projects/<pid>/``."""
    mounted = Path("/data/projects")
    if mounted.exists():
        return str(mounted)
    candidate = Path(__file__).resolve().parents[2] / "data" / "projects"
    return str(candidate)


def get_skill_manager() -> SkillManager:
    """Singleton accessor for SkillManager."""
    global _instance
    if _instance is None:
        shared_path = os.environ.get("BRAIN_SKILLS_DIR") or _default_shared_path()
        project_root = os.environ.get("BRAIN_PROJECT_SKILLS_ROOT") or _default_project_root()
        _instance = SkillManager(shared_path, project_root=project_root)
        _instance.scan_and_load_skills()
    return _instance

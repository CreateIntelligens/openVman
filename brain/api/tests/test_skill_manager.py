from __future__ import annotations

from pathlib import Path

from tools.skill import SkillRef
from tools.skill_manager import SkillManager


def _write_skill(skill_dir: Path, skill_id: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "skill.yaml").write_text(
        (
            f"id: {skill_id}\n"
            f"name: {skill_id}\n"
            "description: test skill\n"
            'version: "0.1.0"\n'
            "tools:\n"
            f"  - name: {skill_id}_action\n"
            "    description: run\n"
            "    parameters:\n"
            "      type: object\n"
            "      properties: {}\n"
        ),
        encoding="utf-8",
    )
    (skill_dir / "main.py").write_text(
        (
            f"def {skill_id}_action(args):\n"
            "    return {'ok': True}\n"
        ),
        encoding="utf-8",
    )


def test_get_skill_prefers_project_scope_when_project_id_is_provided(tmp_path: Path) -> None:
    shared_dir = tmp_path / "shared"
    project_root = tmp_path / "projects"
    _write_skill(shared_dir / "demo", "demo")
    _write_skill(project_root / "proj-a" / "skills" / "demo", "demo")

    manager = SkillManager(str(shared_dir), project_root=str(project_root))
    manager.scan_and_load_skills()
    manager.reload_project_skills("proj-a")

    shared_skill = manager.get_skill(SkillRef(skill_id="demo", scope="shared"))
    project_skill = manager.get_skill(SkillRef(skill_id="demo", project_id="proj-a"))

    assert shared_skill is not None
    assert project_skill is not None
    assert shared_skill.scope == "shared"
    assert project_skill.scope == "project"
    assert project_skill.project_id == "proj-a"


def test_reload_project_skills_replaces_previous_project_scope(tmp_path: Path) -> None:
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir(parents=True, exist_ok=True)
    project_root = tmp_path / "projects"
    _write_skill(project_root / "proj-a" / "skills" / "alpha", "alpha")
    _write_skill(project_root / "proj-b" / "skills" / "beta", "beta")

    manager = SkillManager(str(shared_dir), project_root=str(project_root))
    manager.scan_and_load_skills()
    manager.reload_project_skills("proj-a")

    assert manager.get_skill(SkillRef(skill_id="alpha", scope="project", project_id="proj-a")) is not None

    manager.reload_project_skills("proj-b")

    assert manager.get_skill(SkillRef(skill_id="alpha", scope="project", project_id="proj-a")) is None
    beta_skill = manager.get_skill(SkillRef(skill_id="beta", scope="project", project_id="proj-b"))
    assert beta_skill is not None
    assert beta_skill.scope == "project"

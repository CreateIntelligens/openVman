"""Shared files must retain admin changes across independent Brain workers."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest
from infra.file_lock import atomic_write_text, file_lock
from tools.skill import SkillRef
from tools.skill_manager import SkillManager
from tools.tool_registry import ToolRegistry


def _skill(path: Path, skill_id: str = "demo") -> None:
    path.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path / "skill.yaml", (
        f"id: {skill_id}\nname: {skill_id}\ntools:\n"
        f"  - name: run\n    description: test\n"
        "    parameters: {type: object}\n"
    ))
    atomic_write_text(path / "main.py", "def run(args):\n    return 'first'\n")


def _registry_worker(shared: str, connection) -> None:
    import tools.skill_manager as managers
    import tools.tool_registry as registries

    managers._instance = SkillManager(shared)
    managers._instance.scan_and_load_skills()
    registries._registry = ToolRegistry()
    registries._sync_invalidated = True
    registry = registries.get_tool_registry()
    connection.send([tool.name for tool in registry.list_tools()])
    while connection.recv():
        registry = registries.get_tool_registry()
        connection.send({tool.name: tool.handler({}) for tool in registry.list_tools()})
    connection.close()


def test_chat_registry_notices_admin_changes_without_invalidation(tmp_path):
    shared = tmp_path / "shared"
    _skill(shared / "demo")
    context = multiprocessing.get_context("fork")
    parent, child = context.Pipe()
    process = context.Process(target=_registry_worker, args=(str(shared), child))
    process.start()
    try:
        assert parent.poll(10)
        assert parent.recv() == ["demo:run"]
        manager = SkillManager(str(shared))
        manager.scan_and_load_skills()
        manager.disable_skill(SkillRef("demo"), ToolRegistry())
        parent.send(True)
        assert parent.poll(10)
        assert parent.recv() == {}

        # A new manager models a restart; disabling must survive it.
        restarted = SkillManager(str(shared))
        restarted.scan_and_load_skills()
        assert restarted.get_skill(SkillRef("demo")).enabled is False
        restarted.enable_skill(SkillRef("demo"), ToolRegistry())
        atomic_write_text(shared / "demo" / "main.py", "def run(args):\n    return 'other'\n")
        _skill(shared / "new", "new")
        parent.send(True)
        assert parent.poll(10)
        assert parent.recv() == {"demo:run": "other", "new:run": "first"}
        restarted.delete_skill(SkillRef("demo"), ToolRegistry())
        parent.send(True)
        assert parent.poll(10)
        assert parent.recv() == {"new:run": "first"}
    finally:
        if process.is_alive():
            parent.send(False)
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
        parent.close()
    assert process.exitcode == 0


def test_switching_projects_also_refreshes_shared_skills(tmp_path):
    shared = tmp_path / "shared"
    _skill(shared / "demo")
    reader = SkillManager(str(shared))
    reader.scan_and_load_skills()
    reader.reload_project_skills("one")
    writer = SkillManager(str(shared))
    writer.scan_and_load_skills()
    writer.disable_skill(SkillRef("demo"), ToolRegistry())
    reader.reload_project_skills("two")
    assert reader.get_skill(SkillRef("demo")).enabled is False


def _metadata_writer(path: str, number: int) -> None:
    import knowledge.doc_meta as metadata

    metadata.get_doc_meta_path = lambda project_id="default": Path(path)
    for index in range(50):
        metadata.upsert_document_meta(f"{number}-{index}.md", enabled=False)
        metadata.upsert_document_meta("shared.md", language=f"language-{number}")


def test_document_metadata_keeps_concurrent_updates_and_disabled_flag(tmp_path):
    path = tmp_path / ".doc_meta.json"
    atomic_write_text(path, json.dumps({"shared.md": {"enabled": False}}))
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(target=_metadata_writer, args=(str(path), number))
        for number in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        if process.is_alive():
            process.terminate()
            process.join(5)
        assert process.exitcode == 0
    metadata = json.loads(path.read_text())
    assert len(metadata) == 201
    assert all(entry["enabled"] is False for entry in metadata.values())
    assert metadata["shared.md"]["language"].startswith("language-")


def test_atomic_write_failure_preserves_previous_content(monkeypatch, tmp_path):
    import infra.file_lock as locking

    path = tmp_path / "settings.json"
    path.write_text("previous")
    path.chmod(0o600)
    monkeypatch.setattr(locking.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("failed")))
    with pytest.raises(OSError, match="failed"):
        atomic_write_text(path, "new")
    assert path.read_text() == "previous"
    assert list(tmp_path.glob(".write-*")) == []


def test_file_lock_is_reentrant_and_atomic_write_preserves_permissions(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("original")
    path.chmod(0o600)
    with file_lock(path):  # noqa: SIM117 - Exercise nested acquisition explicitly.
        with file_lock(path):
            atomic_write_text(path, "updated")
    assert path.read_text() == "updated"
    assert path.stat().st_mode & 0o777 == 0o600


def test_shared_skill_state_uses_writable_data_outside_readonly_packages(tmp_path):
    shared = tmp_path / "packages"
    skill_dir = shared / "demo"
    _skill(skill_dir)
    manager = SkillManager(str(shared), project_root=str(tmp_path / "data" / "projects"))
    manager.scan_and_load_skills()
    for file in skill_dir.iterdir():
        file.chmod(0o444)
    skill_dir.chmod(0o555)
    shared.chmod(0o555)
    try:
        manager.disable_skill(SkillRef("demo"), ToolRegistry())
        restarted = SkillManager(str(shared), project_root=str(tmp_path / "data" / "projects"))
        restarted.scan_and_load_skills()
        assert restarted.get_skill(SkillRef("demo")).enabled is False
        assert len(list((tmp_path / "data" / "skill_states").glob("*.json"))) == 1
        assert {path.name for path in skill_dir.iterdir()} == {"skill.yaml", "main.py"}
    finally:
        shared.chmod(0o755)
        skill_dir.chmod(0o755)


def test_skill_state_keeps_shared_and_project_scopes_independent(tmp_path):
    shared = tmp_path / "shared"
    projects = tmp_path / "data" / "projects"
    _skill(shared / "demo")
    _skill(projects / "first" / "skills" / "demo")
    _skill(projects / "second" / "skills" / "demo")
    manager = SkillManager(str(shared), project_root=str(projects))
    manager.scan_and_load_skills()
    manager.reload_project_skills("first")
    manager.disable_skill(SkillRef("demo", "project", "first"), ToolRegistry())
    assert manager.get_skill(SkillRef("demo", "shared")).enabled is True
    manager.reload_project_skills("second")
    assert manager.get_skill(SkillRef("demo", "project", "second")).enabled is True
    manager.reload_all(ToolRegistry(), project_id="first")
    assert manager.get_skill(SkillRef("demo", "project", "first")).enabled is False
    assert manager.get_skill(SkillRef("demo", "shared")).enabled is True

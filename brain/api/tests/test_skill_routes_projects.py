"""HTTP skill administration must preserve the requested project scope."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _write_skill(directory: Path, name: str):
    directory.mkdir(parents=True)
    (directory / "skill.yaml").write_text(
        f"id: {name}\nname: {name}\ndescription: test\ntools:\n"
        "  - name: act\n    description: act\n"
        "    parameters: {type: object, properties: {}}\n"
    )
    (directory / "main.py").write_text("def act(args):\n    return {'ok': True}\n")


@pytest.fixture
def client(monkeypatch, tmp_path):
    from routes import tools as routes
    from tools import skill_manager, tool_registry

    shared, projects = tmp_path / "shared", tmp_path / "projects"
    _write_skill(shared / "shared", "shared")
    _write_skill(projects / "alpha" / "skills" / "alpha", "alpha")
    manager = skill_manager.SkillManager(str(shared), str(projects))
    manager.scan_and_load_skills()
    monkeypatch.setattr(skill_manager, "get_skill_manager", lambda: manager)
    monkeypatch.setattr(routes, "get_skill_manager", lambda: manager)
    monkeypatch.setattr(tool_registry, "_registry", tool_registry.ToolRegistry())
    monkeypatch.setattr(tool_registry, "_sync_invalidated", True)
    monkeypatch.setattr(tool_registry, "_last_synced_project", None)
    monkeypatch.setattr(tool_registry, "_last_skill_revision", None)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app, headers={"X-Internal-Token": "test-internal-token"}) as session:
        yield session


def test_project_skill_list_toggle_and_files_use_requested_project(client):
    response = client.get("/brain/tools", params={"project_id": "alpha"})
    assert response.status_code == 200
    assert {tool["name"] for tool in response.json()["skill_tools"]} == {
        "proj:alpha:alpha:act", "shared:act",
    }
    assert {skill["id"] for skill in response.json()["skills"]} == {"alpha", "shared"}
    query = {"scope": "project", "project_id": "alpha"}
    files = client.get("/brain/skills/alpha/files", params=query)
    assert files.status_code == 200
    assert "id: alpha" in files.json()["files"]["skill.yaml"]
    toggled = client.patch("/brain/skills/alpha/toggle", params=query)
    assert toggled.status_code == 200
    assert toggled.json()["enabled"] is False
    assert {tool["name"] for tool in client.get("/brain/tools", params={"project_id": "alpha"}).json()["skill_tools"]} == {"shared:act"}
    assert client.patch("/brain/skills/alpha/toggle", params=query).json()["enabled"] is True


def test_shared_skill_list_toggle_and_files_still_work(client):
    assert {tool["name"] for tool in client.get("/brain/tools").json()["skill_tools"]} == {"shared:act"}
    response = client.get("/brain/skills/shared/files", params={"scope": "shared"})
    assert response.status_code == 200
    toggled = client.patch("/brain/skills/shared/toggle", params={"scope": "shared"})
    assert toggled.status_code == 200
    assert toggled.json()["enabled"] is False
    assert client.get("/brain/tools").json()["skill_tools"] == []


def test_worker_settings_keep_admin_single_process():
    from config import BrainSettings
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="admin"):
        BrainSettings(_env_file=None, brain_role="admin", brain_workers=2)
    cfg = BrainSettings(_env_file=None, brain_role="chat", brain_workers=4)
    assert cfg.brain_role == "chat"
    assert cfg.brain_workers == 4

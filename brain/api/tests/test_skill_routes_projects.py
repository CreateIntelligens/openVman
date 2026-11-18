"""HTTP skill administration must preserve the requested project scope."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
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


@pytest.mark.parametrize(
    "skill_id",
    ["../../shared/evil", "../alpha/evil", "..", "a/b", "evil-name", "9lives", "x" * 65, ""],
)
def test_create_rejects_skill_ids_that_are_not_plain_names(client, tmp_path, skill_id):
    # 2026-11-18：技能 ID 直接當目錄名稱，帶 ../ 能寫進共用技能或別的專案。
    response = client.post(
        "/brain/skills",
        json={"skill_id": skill_id, "name": "x", "scope": "project", "project_id": "alpha"},
    )

    assert response.status_code == 422
    assert {path.name for path in (tmp_path / "shared").iterdir()} == {"shared"}
    assert {path.name for path in (tmp_path / "projects").iterdir()} == {"alpha"}
    assert {path.name for path in (tmp_path / "projects" / "alpha" / "skills").iterdir()} == {"alpha"}


@pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
def test_skill_routes_reject_unsafe_skill_ids(client, method):
    suffix = {"GET": "/files", "PUT": "/files", "PATCH": "/toggle", "DELETE": ""}[method]
    response = client.request(
        method,
        f"/brain/skills/evil-name{suffix}",
        params={"scope": "project", "project_id": "alpha"},
        json={"files": {}} if method == "PUT" else None,
    )

    assert response.status_code == 422


def test_project_ids_are_normalized_and_dot_segments_refused(client, tmp_path):
    padded = client.post(
        "/brain/skills",
        json={"skill_id": "padded", "name": "x", "scope": "project", "project_id": " alpha "},
    )
    dotted = client.post(
        "/brain/skills",
        json={"skill_id": "dotted", "name": "x", "scope": "project", "project_id": ".."},
    )

    assert padded.status_code == 200
    assert (tmp_path / "projects" / "alpha" / "skills" / "padded").is_dir()
    assert dotted.status_code == 400
    assert not (tmp_path / "skills").exists()


def test_create_keeps_name_and_description_out_of_code(client, tmp_path):
    # 名稱以前用 str.format 拼進 main.py 的 docstring，帶 """ 就能在載入時執行程式。
    marker = tmp_path / "pwned"
    name = f'x"""\nopen({str(marker)!r}, "w").write("1")\n"""'
    response = client.post(
        "/brain/skills",
        json={
            "skill_id": "injected",
            "name": name,
            "description": "a: b\nmalicious: [1",
            "scope": "project",
            "project_id": "alpha",
        },
    )

    assert response.status_code == 200
    skill_dir = tmp_path / "projects" / "alpha" / "skills" / "injected"
    assert name not in (skill_dir / "main.py").read_text()
    assert not marker.exists()
    files = client.get(
        "/brain/skills/injected/files", params={"scope": "project", "project_id": "alpha"},
    ).json()["files"]
    manifest = yaml.safe_load(files["skill.yaml"])
    assert manifest["name"] == name
    assert manifest["description"] == "a: b\nmalicious: [1"


@pytest.mark.parametrize(
    ("manifest", "reason"),
    [
        ("id: shared\nname: hijack\ntools: []\n", "id must stay"),
        ("id: [unclosed\n", "Invalid skill manifest YAML"),
        ("- just\n- a list\n", "must be a mapping"),
        ("id: alpha\ntools:\n  - description: no name\n", "Invalid tools"),
    ],
)
def test_update_rejects_bad_manifests_without_touching_disk(client, tmp_path, manifest, reason):
    # 以前先寫檔再驗：改 id 會冒用別的技能，YAML 壞掉回 500 且之後每次載入都失敗。
    manifest_path = tmp_path / "projects" / "alpha" / "skills" / "alpha" / "skill.yaml"
    before = manifest_path.read_text()

    response = client.put(
        "/brain/skills/alpha/files",
        params={"scope": "project", "project_id": "alpha"},
        json={"files": {"skill.yaml": manifest}},
    )

    assert response.status_code == 400
    assert reason in response.json()["detail"]
    assert manifest_path.read_text() == before
    reloaded = client.get("/brain/tools", params={"project_id": "alpha"})
    assert {skill["id"] for skill in reloaded.json()["skills"]} == {"alpha", "shared"}


def test_list_and_reload_use_the_normalized_project_id(client):
    listed = client.get("/brain/tools", params={"project_id": " alpha "})
    reloaded = client.post("/brain/skills/reload", params={"project_id": " alpha "})
    dotted = client.get("/brain/tools", params={"project_id": ".."})

    assert {skill["id"] for skill in listed.json()["skills"]} == {"alpha", "shared"}
    assert "alpha" in reloaded.json()["skills"]
    assert dotted.status_code == 400

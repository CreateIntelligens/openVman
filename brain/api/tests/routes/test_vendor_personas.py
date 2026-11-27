"""Exercise the vendor personae and file requests received from Backend."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge.workspace import content_hash, ensure_workspace_scaffold
from routes import knowledge, personas


def test_vendor_persona_soul_read_write_and_summary():
    workspace = ensure_workspace_scaffold("default")
    support = workspace / "personas" / "support"
    support.mkdir()
    files = {
        workspace / "SOUL.md": "# 預設人設",
        support / "SOUL.md": "# 客服人設",
        support / "AGENTS.md": "內部工作規則",
        support / "MEMORY.md": "內部記憶",
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")

    app = FastAPI()
    app.include_router(personas.router)
    client = TestClient(app)
    headers = {"X-Internal-Token": "test-internal-token", "X-OpenVMan-Vendor": "1"}
    assert client.get("/brain/personas", headers=headers).json() == {
        "personas": [
            {"persona_id": "default", "label": "預設角色", "is_default": True},
            {"persona_id": "support", "label": "客服人設", "is_default": False},
        ],
        "persona_count": 2,
    }
    route = "/brain/personas/soul"
    for persona_id, path in (("default", workspace / "SOUL.md"), ("support", support / "SOUL.md")):
        assert client.get(route, params={"persona_id": persona_id}, headers=headers).json() == {
            "content": files[path], "content_hash": content_hash(files[path]),
        }
        put = client.put(route, headers=headers, json={
            "persona_id": persona_id, "content": "更新後的人設",
        })
        assert put.status_code == 200
        assert path.read_text(encoding="utf-8") == "更新後的人設"
    assert client.put(route, headers=headers, json={
        "persona_id": "support", "content": "越權", "path": "personas/support/AGENTS.md",
    }).status_code == 422
    assert (support / "AGENTS.md").read_text(encoding="utf-8") == "內部工作規則"
    assert (support / "MEMORY.md").read_text(encoding="utf-8") == "內部記憶"
    assert "avatar_char_id" in client.get(
        "/brain/personas", headers={"X-Internal-Token": "test-internal-token"},
    ).json()["personas"][0]


def test_vendor_file_operations_refuse_files_aliased_to_core_documents():
    workspace = ensure_workspace_scaffold("default")
    private = workspace / "AGENTS.md"
    private.write_text("內部工作規則", encoding="utf-8")
    (workspace / "knowledge" / "alias.md").symlink_to(private)
    support = workspace / "personas" / "support"
    support.mkdir()
    (support / "SOUL.md").symlink_to(private)

    app = FastAPI()
    app.include_router(personas.router)
    app.include_router(knowledge.router)
    client = TestClient(app)
    headers = {"X-Internal-Token": "test-internal-token", "X-OpenVMan-Vendor": "1"}
    assert client.get(
        "/brain/personas/soul", headers=headers, params={"persona_id": "support"},
    ).status_code == 403
    assert client.put("/brain/personas/soul", headers=headers, json={
        "persona_id": "support", "content": "越權",
    }).status_code == 403
    assert client.get(
        "/brain/knowledge/document", headers=headers, params={"path": "knowledge/alias.md"},
    ).status_code == 403
    assert client.put("/brain/knowledge/document", headers=headers, json={
        "path": "knowledge/alias.md", "content": "越權",
    }).status_code == 403
    assert client.get("/brain/knowledge/base/documents", headers=headers).json()["documents"] == []
    assert private.read_text(encoding="utf-8") == "內部工作規則"


@pytest.mark.parametrize("padding", [" ", "\t"])
@pytest.mark.parametrize(("method", "route", "padded_key", "fields"), [
    ("GET", "document", "path", {"path": "knowledge/guide.md"}),
    ("PUT", "document", "path", {"path": "knowledge/guide.md", "content": "更新"}),
    ("DELETE", "document", "path", {"path": "knowledge/guide.md"}),
    ("PATCH", "document/meta", "path", {"path": "knowledge/guide.md", "enabled": False}),
    ("POST", "move", "source_path", {"source_path": "knowledge/guide.md", "target_path": "knowledge/moved.md"}),
    ("POST", "move", "target_path", {"source_path": "knowledge/guide.md", "target_path": "knowledge/moved.md"}),
    ("POST", "directory", "path", {"path": "knowledge/new-folder", "content": ""}),
    ("DELETE", "directory", "path", {"path": "knowledge/folder"}),
])
def test_vendor_knowledge_rejects_whitespace(method, route, padded_key, fields, padding, monkeypatch):
    workspace = ensure_workspace_scaffold("default")
    guide = workspace / "knowledge" / "guide.md"
    guide.write_text("原始內容", encoding="utf-8")
    (workspace / "knowledge" / "folder").mkdir()
    monkeypatch.setattr(knowledge, "schedule_reindex", lambda *_: None)
    monkeypatch.setattr(knowledge, "_background_rename_document", AsyncMock())
    app = FastAPI()
    app.include_router(knowledge.router)
    headers = {"X-Internal-Token": "test-internal-token", "X-OpenVMan-Vendor": "1"}
    data = {**fields, padded_key: fields[padded_key] + padding}
    kwargs = {"params": data} if method in {"GET", "DELETE"} else {"json": data}
    response = TestClient(app).request(method, f"/brain/knowledge/{route}", headers=headers, **kwargs)
    assert response.status_code == 403, response.text
    assert guide.read_text(encoding="utf-8") == "原始內容"

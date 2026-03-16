"""Tests for infra.project_admin — CRUD, default protection, format validation."""

from __future__ import annotations

import shutil
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


@pytest.fixture(autouse=True)
def _isolate_data_root(tmp_path, monkeypatch):
    """Redirect project data root to a temp directory for all tests."""
    monkeypatch.setattr("infra.project_context._DATA_ROOT", tmp_path / "projects")
    monkeypatch.setattr("infra.project_admin.get_data_root", lambda: tmp_path / "projects")

    # Also patch resolve_project_context to use the temp root
    from infra.project_context import ProjectContext

    def _resolve(pid=None):
        from infra.project_context import normalize_project_id
        pid = normalize_project_id(pid)
        root = tmp_path / "projects" / pid
        return ProjectContext(
            project_id=pid,
            project_root=root,
            workspace_root=root / "workspace",
            lancedb_path=root / "lancedb",
            session_db_path=root / "sessions.db",
            index_state_path=root / "knowledge_index_state.json",
        )

    monkeypatch.setattr("infra.project_context.resolve_project_context", _resolve)
    monkeypatch.setattr("infra.project_admin.resolve_project_context", _resolve)

    # Stub workspace scaffold to just create the directory
    def _fake_scaffold(project_id="default"):
        ctx = _resolve(project_id)
        ctx.workspace_root.mkdir(parents=True, exist_ok=True)
        (ctx.workspace_root / "SOUL.md").write_text("# Test Soul", encoding="utf-8")
        return ctx.workspace_root

    # Patch in knowledge.workspace for create_project
    monkeypatch.setattr("knowledge.workspace.ensure_workspace_scaffold", _fake_scaffold)
    monkeypatch.setattr("knowledge.workspace.get_workspace_root", lambda pid="default": _resolve(pid).workspace_root)


from infra.project_admin import (
    create_project,
    delete_project,
    get_project_info,
    list_projects,
)


class TestListProjects:
    def test_empty(self):
        assert list_projects() == []

    def test_lists_created_projects(self):
        create_project("alpha", "Alpha Label")
        create_project("beta")
        projects = list_projects()
        ids = [p["project_id"] for p in projects]
        assert "alpha" in ids
        assert "beta" in ids


class TestCreateProject:
    def test_creates_workspace(self):
        result = create_project("new-proj", "My Project")
        assert result["status"] == "ok"
        assert result["project_id"] == "new-proj"
        assert result["label"] == "My Project"

    def test_duplicate_raises(self):
        create_project("dup")
        with pytest.raises(ValueError, match="已存在"):
            create_project("dup")

    def test_invalid_id_raises(self):
        with pytest.raises(ValueError, match="project_id"):
            create_project("bad/id")


class TestDeleteProject:
    def test_deletes_existing(self):
        create_project("to-delete")
        result = delete_project("to-delete")
        assert result["status"] == "ok"
        assert list_projects() == [] or all(
            p["project_id"] != "to-delete" for p in list_projects()
        )

    def test_default_cannot_be_deleted(self):
        with pytest.raises(ValueError, match="default"):
            delete_project("default")

    def test_nonexistent_raises(self):
        with pytest.raises(ValueError, match="不存在"):
            delete_project("ghost")


class TestGetProjectInfo:
    def test_returns_metadata(self):
        create_project("info-test", "Info Test")
        info = get_project_info("info-test")
        assert info["project_id"] == "info-test"
        assert info["label"] == "Info Test"
        assert isinstance(info["document_count"], int)
        assert isinstance(info["persona_count"], int)

    def test_nonexistent_raises(self):
        with pytest.raises(ValueError, match="不存在"):
            get_project_info("nope")

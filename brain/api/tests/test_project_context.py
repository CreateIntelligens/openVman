"""Tests for infra.project_context — path resolution, DB isolation, session isolation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from infra.project_context import (
    ProjectContext,
    normalize_project_id,
    resolve_project_context,
    get_data_root,
    reset_caches,
)


class TestNormalizeProjectId:
    def test_empty_returns_default(self):
        assert normalize_project_id("") == "default"
        assert normalize_project_id(None) == "default"
        assert normalize_project_id("  ") == "default"

    def test_valid_ids(self):
        assert normalize_project_id("my-project") == "my-project"
        assert normalize_project_id("Project_1.0") == "Project_1.0"
        assert normalize_project_id("a") == "a"
        assert normalize_project_id("A" * 64) == "A" * 64

    def test_invalid_ids(self):
        with pytest.raises(ValueError, match="project_id"):
            normalize_project_id("has space")
        with pytest.raises(ValueError, match="project_id"):
            normalize_project_id("a/b")
        with pytest.raises(ValueError, match="project_id"):
            normalize_project_id("a" * 65)
        with pytest.raises(ValueError, match="project_id"):
            normalize_project_id("hello!")


class TestResolveProjectContext:
    def test_default_project(self):
        ctx = resolve_project_context("default")
        assert ctx.project_id == "default"
        assert ctx.workspace_root == ctx.project_root / "workspace"
        assert ctx.lancedb_path == ctx.project_root / "lancedb"
        assert ctx.session_db_path == ctx.project_root / "sessions.db"
        assert ctx.index_state_path == ctx.project_root / "knowledge_index_state.json"

    def test_custom_project(self):
        ctx = resolve_project_context("client-A")
        assert ctx.project_id == "client-A"
        assert "client-A" in str(ctx.project_root)

    def test_none_resolves_to_default(self):
        ctx = resolve_project_context(None)
        assert ctx.project_id == "default"

    def test_paths_are_isolated(self):
        a = resolve_project_context("proj-a")
        b = resolve_project_context("proj-b")
        assert a.workspace_root != b.workspace_root
        assert a.lancedb_path != b.lancedb_path
        assert a.session_db_path != b.session_db_path

    def test_frozen(self):
        ctx = resolve_project_context("test")
        with pytest.raises(AttributeError):
            ctx.project_id = "other"


class TestDataRoot:
    def test_returns_path(self):
        root = get_data_root()
        assert root.name == "projects"
        assert root.parent.name == "data"

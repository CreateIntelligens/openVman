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
    resolve_embedding_index_state_path,
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

    def test_default_alias_and_empty_resolve_to_configured_project(self, monkeypatch):
        from config import get_settings

        monkeypatch.setattr(get_settings(), "default_project_id", "proj-hospital")
        assert normalize_project_id(None) == "proj-hospital"
        assert normalize_project_id("") == "proj-hospital"
        assert normalize_project_id("default") == "proj-hospital"
        assert normalize_project_id("other") == "other"
        assert resolve_project_context("default").project_root.name == "proj-hospital"

    def test_invalid_configured_default_falls_back_to_alias(self, monkeypatch):
        from config import get_settings

        monkeypatch.setattr(get_settings(), "default_project_id", "bad id/with slash")
        assert normalize_project_id(None) == "default"

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


class TestEmbeddingIndexStatePath:
    def test_default_write_identity_uses_the_gemma_path(self):
        path = resolve_embedding_index_state_path("default")

        assert path.name == "knowledge_index_state__gemma.json"

    def test_alias_and_its_identity_share_the_namespaced_path(self):
        from config import get_settings

        identity = get_settings().resolved_embedding_write_identity

        assert resolve_embedding_index_state_path("default", "gemma").name == (
            "knowledge_index_state__gemma.json"
        )
        assert resolve_embedding_index_state_path("default", identity).name == (
            "knowledge_index_state__gemma.json"
        )

    def test_unknown_identity_gets_an_isolated_path(self):
        path = resolve_embedding_index_state_path(
            "default", "bge:BAAI/bge-m3:1024:float32:l2:document:default"
        )

        assert path.name.startswith("knowledge_index_state__emb_")


def test_startup_migration_marks_the_configured_default_without_recreating_default(
    tmp_path, monkeypatch,
):
    import scripts.migrate_to_projects as migration
    from config import get_settings

    monkeypatch.setattr("infra.project_context._DATA_ROOT", tmp_path / "projects")
    monkeypatch.setattr(get_settings(), "default_project_id", "proj-hospital")
    # 舊資料搬移的各步驟碰的是真實路徑，這裡只驗 marker 落點。
    for step in ("_migrate_workspace", "_migrate_lancedb", "_migrate_sessions_db",
                 "_migrate_index_state", "_migrate_learnings"):
        monkeypatch.setattr(migration, step, lambda: False)

    migration.run_migration()

    assert (tmp_path / "projects" / "proj-hospital" / ".migrated").exists()
    assert not (tmp_path / "projects" / "default").exists()

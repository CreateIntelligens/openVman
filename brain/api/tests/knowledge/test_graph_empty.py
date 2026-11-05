from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from knowledge.graph import EmptyGraphError, load_project_graph, load_project_status, load_project_summary
from routes.knowledge import _run_graph_rebuild


@pytest.mark.asyncio
async def test_run_graph_rebuild_empty(monkeypatch, tmp_path):
    import knowledge.workspace
    import routes.knowledge

    # Mock workspace root
    monkeypatch.setattr(knowledge.workspace, "get_workspace_root", lambda project_id="default": tmp_path)

    # Mock rebuild_project_graph to raise EmptyGraphError
    def mock_rebuild(project_id):
        raise EmptyGraphError("no nodes")

    monkeypatch.setattr(routes.knowledge, "rebuild_project_graph", mock_rebuild)
    monkeypatch.setattr(routes.knowledge, "has_stale_documents", lambda project_id: False)

    # Run the rebuild function
    await _run_graph_rebuild("default")

    # Load status, summary, graph
    status = load_project_status("default")
    assert status["state"] == "ready"
    assert status["nodes"] == 0
    assert status["edges"] == 0

    summary = load_project_summary("default")
    assert summary["nodes"] == 0
    assert summary["edges"] == 0

    graph = load_project_graph("default")
    assert graph["nodes"] == []
    assert graph["edges"] == []


def test_graph_scans_keep_their_cache_out_of_the_knowledge_directory(monkeypatch, tmp_path):
    """graphify 預設把快取寫在被掃描的資料夾，文件樹就會多一個 graphify-out。"""
    import knowledge.graph
    import knowledge.workspace

    root = tmp_path / "workspace"
    (root / "knowledge").mkdir(parents=True)
    monkeypatch.setattr(knowledge.graph, "get_workspace_root", lambda project_id="default": root)
    calls = []

    def fake_detect(path, **kwargs):
        calls.append((path, kwargs.get("cache_root")))
        return {"files": {}}

    monkeypatch.setattr(knowledge.graph, "detect", fake_detect)

    store = SimpleNamespace(load=lambda *args, **kwargs: {})
    list(knowledge.graph._GraphItemSource("default", store).pending())
    with pytest.raises(EmptyGraphError):
        knowledge.graph.rebuild_project_graph("default")

    assert len(calls) >= 2
    assert all(cache_root == root for _, cache_root in calls)


def test_system_folders_are_not_listed_as_knowledge_folders(monkeypatch, tmp_path):
    import knowledge.knowledge_admin as admin

    root = tmp_path / "workspace"
    (root / "knowledge" / "graphify-out" / "cache").mkdir(parents=True)
    (root / "knowledge" / ".qa_images").mkdir()
    (root / "knowledge" / "products").mkdir()
    monkeypatch.setattr(admin, "ensure_workspace_scaffold", lambda project_id="default": root)

    assert admin.list_knowledge_base_directories() == ["knowledge/products"]

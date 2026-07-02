from __future__ import annotations

import asyncio
from pathlib import Path
import sys

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

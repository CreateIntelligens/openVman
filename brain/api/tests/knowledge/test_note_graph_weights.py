"""優化點 3: note_graph stores per-neighbour relation + confidence.

The file-level adjacency table must keep, per related file, the relation that
linked them and the edge confidence — so Graph RAG can rank neighbours
(user-written ``references`` first, then high-confidence inferences) instead of
taking them in arbitrary dict order.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


@pytest.fixture(autouse=True)
def _restore_graph_modules():
    """Undo this file's stub-and-reimport of knowledge.graph.

    ``_load_graph`` reimports knowledge.graph with knowledge.graph_extractor
    stubbed to no-op lambdas. monkeypatch restores graph_extractor, but the
    freshly imported knowledge.graph stays in sys.modules bound to those stubs,
    poisoning later tests (e.g. _GraphWorker._extract_one_file becomes a no-op).
    Drop both after each test so the next importer gets the real modules.
    """
    yield
    for name in ("knowledge.graph", "knowledge.graph_extractor"):
        sys.modules.pop(name, None)


class _CapturingDB:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}

    def create_table(self, name, data, mode="overwrite"):
        self.tables[name] = data
        return types.SimpleNamespace()


def _load_graph(monkeypatch, db: _CapturingDB):
    """Import knowledge.graph with heavy deps stubbed."""
    stub_symbols = {
        "graphify.analyze": ["god_nodes", "surprising_connections"],
        "graphify.build": ["build_from_json"],
        "graphify.cluster": ["cluster", "score_all"],
        "graphify.detect": ["detect"],
        "graphify.export": ["to_canvas", "to_html", "to_json", "to_obsidian"],
        "graphify.extract": ["collect_files", "extract"],
        "knowledge.graph_extractor": [
            "postprocess_fragments",
            "_extract_one_file",
            "LLM_CONCURRENCY",
            "_relative",
        ],
    }
    for mod, names in stub_symbols.items():
        stub = types.ModuleType(mod)
        for name in names:
            setattr(stub, name, lambda *a, **k: None)
        monkeypatch.setitem(sys.modules, mod, stub)

    fake_infra = types.ModuleType("infra.db")
    fake_infra.get_db = lambda project_id="default": db
    monkeypatch.setitem(sys.modules, "infra.db", fake_infra)

    fake_ws = types.ModuleType("knowledge.workspace")
    fake_ws.ensure_workspace_scaffold = lambda project_id="default": Path("/tmp")
    fake_ws.get_workspace_root = lambda project_id="default": Path("/tmp")
    monkeypatch.setitem(sys.modules, "knowledge.workspace", fake_ws)

    import importlib

    sys.modules.pop("knowledge.graph", None)
    return importlib.import_module("knowledge.graph")


def _merged_two_neighbours():
    """diabetes.md links to insulin.md (references, 1.0) and diet.md (related, 0.7)."""
    return {
        "nodes": [
            {"id": "diabetes", "source_file": "diabetes.md"},
            {"id": "insulin", "source_file": "insulin.md"},
            {"id": "diet", "source_file": "diet.md"},
        ],
        "edges": [
            {
                "source": "diabetes",
                "target": "insulin",
                "relation": "references",
                "confidence_score": 1.0,
            },
            {
                "source": "diabetes",
                "target": "diet",
                "relation": "conceptually_related_to",
                "confidence_score": 0.7,
            },
        ],
    }


def test_note_graph_row_keeps_per_neighbour_relation_and_confidence(monkeypatch):
    db = _CapturingDB()
    graph = _load_graph(monkeypatch, db)

    graph._build_note_graph_table(_merged_two_neighbours(), "default")

    rows = {r["source_file"]: r for r in db.tables[graph.NOTE_GRAPH_TABLE]}
    diabetes = rows["diabetes.md"]

    # related_files and the parallel weight arrays must align by index.
    by_file = dict(
        zip(diabetes["related_files"], diabetes["neighbour_confidence"])
    )
    assert by_file["insulin.md"] == 1.0
    assert by_file["diet.md"] == 0.7

    rel_by_file = dict(
        zip(diabetes["related_files"], diabetes["neighbour_relations"])
    )
    assert rel_by_file["insulin.md"] == "references"

"""優化點 2: vector-guided neighbour chunk retrieval.

When the graph expansion fetches chunks from a neighbour file, it should pass
the user's query vector to LanceDB so the chunks returned are the ones in that
file most relevant to the question — not blindly the file's first segments.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class _FakeSearch:
    """Records how ``table.search`` was invoked and returns canned rows."""

    def __init__(self, rows: list[dict], calls: list):
        self._rows = rows
        self._calls = calls

    def where(self, _clause: str) -> "_FakeSearch":
        return self

    def limit(self, _n: int) -> "_FakeSearch":
        return self

    def to_list(self) -> list[dict]:
        return self._rows


class _FakeTable:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self.search_calls: list = []

    def search(self, query_vector=None):
        self.search_calls.append(query_vector)
        return _FakeSearch(self._rows, self.search_calls)


def _row(path: str) -> dict:
    return {
        "text": "段落",
        "vector": [0.0],
        "metadata": json.dumps({"path": path, "title": "標題"}),
    }


def _stub_infra(monkeypatch: pytest.MonkeyPatch, table: _FakeTable) -> None:
    fake_db = types.ModuleType("infra.db")
    fake_db.get_knowledge_table = lambda project_id: table
    fake_db.parse_record_metadata = lambda row: json.loads(row["metadata"])
    monkeypatch.setitem(sys.modules, "infra.db", fake_db)


def _load_knowledge_tools():
    import importlib

    return importlib.import_module("tools.builtin.knowledge_tools")


def test_fetch_chunks_passes_query_vector_to_search(monkeypatch):
    table = _FakeTable([_row("notes/diabetes.md")])
    _stub_infra(monkeypatch, table)
    kt = _load_knowledge_tools()

    query_vector = [0.42, 0.13, 0.99]
    kt._fetch_chunks_by_file(
        "notes/diabetes.md",
        limit=2,
        project_id="default",
        query_vector=query_vector,
    )

    assert table.search_calls == [query_vector]


def test_fetch_chunks_without_vector_falls_back_to_plain_search(monkeypatch):
    table = _FakeTable([_row("notes/diabetes.md")])
    _stub_infra(monkeypatch, table)
    kt = _load_knowledge_tools()

    kt._fetch_chunks_by_file("notes/diabetes.md", limit=2, project_id="default")

    assert table.search_calls == [None]


def test_expand_via_graph_threads_query_vector_into_fetch(monkeypatch):
    """The query vector reaches _fetch_chunks_by_file via the closure."""
    table = _FakeTable([_row("notes/insulin.md")])
    _stub_infra(monkeypatch, table)
    kt = _load_knowledge_tools()

    # expand_with_graph just invokes the fetch closure for a neighbour file.
    fake_graph_rag = types.ModuleType("knowledge.graph_rag")

    def fake_expand(hits, project_id, fetch_chunks):
        return fetch_chunks("notes/insulin.md", 1)

    fake_graph_rag.expand_with_graph = fake_expand
    monkeypatch.setitem(sys.modules, "knowledge.graph_rag", fake_graph_rag)

    query_vector = [0.7, 0.2, 0.1]
    kt._expand_via_graph(
        [{"path": "notes/diabetes.md"}],
        "default",
        query_vector,
    )

    assert table.search_calls == [query_vector]


# ---------------------------------------------------------------------------
# 優化點 3: relation-weighted graph expansion ordering
# ---------------------------------------------------------------------------


def _load_graph_rag(monkeypatch, rows: list[dict], degree=None):
    """Import graph_rag with note_graph table + graph module stubbed."""

    class _Search:
        def where(self, _c):
            return self

        def to_list(self):
            return rows

    class _Table:
        def search(self):
            return _Search()

    fake_db = types.ModuleType("infra.db")
    fake_db.get_db = lambda project_id="default": types.SimpleNamespace(
        open_table=lambda name: _Table()
    )
    monkeypatch.setitem(sys.modules, "infra.db", fake_db)

    fake_graph = types.ModuleType("knowledge.graph")
    fake_graph.NOTE_GRAPH_TABLE = "note_graph"
    monkeypatch.setitem(sys.modules, "knowledge.graph", fake_graph)

    import importlib

    sys.modules.pop("knowledge.graph_rag", None)
    return importlib.import_module("knowledge.graph_rag")


def test_references_neighbour_ranked_before_low_confidence(monkeypatch):
    """A user-written ``references`` link outranks a weak inferred neighbour."""
    rows = [
        {
            "source_file": "diabetes.md",
            "related_files": ["weak.md", "linked.md"],
            "relations": ["conceptually_related_to", "references"],
            "neighbour_relations": ["conceptually_related_to", "references"],
            "neighbour_confidence": [0.6, 1.0],
        }
    ]
    graph_rag = _load_graph_rag(monkeypatch, rows)

    fetched: list[str] = []

    def fetch_chunks(file_path, limit):
        fetched.append(file_path)
        return [{"path": file_path, "text": "x"}]

    graph_rag.expand_with_graph(
        [{"path": "diabetes.md"}], "default", fetch_chunks, max_related=2
    )

    # linked.md (references, 1.0) must be fetched before weak.md (0.6).
    assert fetched.index("linked.md") < fetched.index("weak.md")


def test_god_node_neighbour_is_excluded(monkeypatch):
    """A hub file linked to too many others is dropped as noise."""
    # index.md is a god node: its own row lists 50 related files.
    god_related = [f"f{i}.md" for i in range(50)]
    rows = [
        {
            "source_file": "diabetes.md",
            "related_files": ["index.md", "linked.md"],
            "relations": ["references", "references"],
            "neighbour_relations": ["references", "references"],
            "neighbour_confidence": [1.0, 1.0],
        },
        {
            "source_file": "index.md",
            "related_files": god_related,
            "relations": ["references"],
            "neighbour_relations": ["references"] * len(god_related),
            "neighbour_confidence": [1.0] * len(god_related),
        },
    ]
    graph_rag = _load_graph_rag(monkeypatch, rows)

    fetched: list[str] = []

    def fetch_chunks(file_path, limit):
        fetched.append(file_path)
        return [{"path": file_path, "text": "x"}]

    graph_rag.expand_with_graph(
        [{"path": "diabetes.md"}], "default", fetch_chunks, max_related=5
    )

    assert "index.md" not in fetched
    assert "linked.md" in fetched

"""Tests for listing persisted memories without optional pandas support."""

from __future__ import annotations

from unittest.mock import MagicMock

from memory import memory


def _table_with_records(records: list[dict]) -> MagicMock:
    table = MagicMock(spec=["to_arrow"])
    table.to_arrow.return_value.to_pylist.return_value = records
    return table


def test_list_memories_uses_arrow_and_excludes_vectors(monkeypatch):
    table = _table_with_records(
        [
            {
                "text": "old",
                "vector": [0.1],
                "date": "2026-08-30",
                "source": "user",
            },
            {
                "text": "undated",
                "vector": [0.2],
                "date": None,
                "source": "system",
            },
            {
                "text": "new",
                "vector": [0.3],
                "date": "2026-09-01",
                "source": "user",
            },
        ]
    )
    monkeypatch.setattr(memory, "get_memories_table", lambda _project_id: table)

    result = memory.list_memories("project-a", page=1, page_size=2)

    assert result == {
        "memories": [
            {"text": "new", "date": "2026-09-01", "source": "user"},
            {"text": "old", "date": "2026-08-30", "source": "user"},
        ],
        "total": 3,
        "page": 1,
        "page_size": 2,
    }
    table.to_arrow.assert_called_once_with()


def test_list_memories_returns_later_pages_and_keeps_undated_last(monkeypatch):
    table = _table_with_records(
        [
            {"text": "undated", "vector": [], "date": None},
            {"text": "new", "vector": [], "date": "2026-09-01"},
            {"text": "old", "vector": [], "date": "2026-08-30"},
        ]
    )
    monkeypatch.setattr(memory, "get_memories_table", lambda _project_id: table)

    result = memory.list_memories("project-a", page=2, page_size=2)

    assert result["memories"] == [{"text": "undated", "date": None}]
    assert result["total"] == 3


def test_list_memories_handles_an_empty_arrow_table(monkeypatch):
    table = _table_with_records([])
    monkeypatch.setattr(memory, "get_memories_table", lambda _project_id: table)

    result = memory.list_memories("project-a", page=1, page_size=20)

    assert result == {
        "memories": [],
        "total": 0,
        "page": 1,
        "page_size": 20,
    }

from __future__ import annotations

import pytest


def test_delete_memory_rejects_lanceql_expression_injection(monkeypatch):
    from memory import memory

    class UnexpectedTable:
        def delete(self, _predicate):  # pragma: no cover - must not execute
            raise AssertionError("unsafe predicate reached LanceDB")

    monkeypatch.setattr(memory, "get_memories_table", lambda _project_id: UnexpectedTable())

    with pytest.raises(ValueError, match="unsupported filter syntax"):
        memory.delete_memory(
            project_id="project-a",
            text="' OR 1=1 --",
        )


def test_delete_memory_uses_exact_safe_predicate(monkeypatch):
    from memory import memory

    predicates: list[str] = []

    class Table:
        def delete(self, predicate):
            predicates.append(predicate)

    monkeypatch.setattr(memory, "get_memories_table", lambda _project_id: Table())

    assert memory.delete_memory(project_id="project-a", text="ordinary memory") is True
    assert predicates == ["text = 'ordinary memory'"]

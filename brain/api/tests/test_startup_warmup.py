import importlib

import pytest

import warmup_state


def _load_main():
    return importlib.import_module("main")


@pytest.fixture(autouse=True)
def _reset_warmup_state():
    warmup_state.reset_warmup_state()
    yield
    warmup_state.reset_warmup_state()


def test_warmup_project_ids_include_projects_with_knowledge_state(monkeypatch):
    main = _load_main()

    monkeypatch.setattr(
        main,
        "list_projects",
        lambda: [
            {"project_id": "default", "document_count": 0, "has_lancedb": False},
            {"project_id": "proj-empty", "document_count": 0, "has_lancedb": False},
            {"project_id": "proj-docs", "document_count": 2, "has_lancedb": False},
            {"project_id": "proj-indexed", "document_count": 0, "has_lancedb": True},
        ],
        raising=False,
    )

    assert main._warmup_project_ids() == ["default", "proj-docs", "proj-indexed"]


@pytest.mark.asyncio
async def test_warmup_resources_runs_retrieval_warmup_for_each_project(monkeypatch):
    main = _load_main()
    ensured: list[str] = []
    warmed: list[str] = []
    maintained: list[str] = []

    monkeypatch.setattr(main, "_warmup_project_ids", lambda: ["default", "proj-active"])
    monkeypatch.setattr(main, "ensure_workspace_scaffold", lambda project_id: None)
    monkeypatch.setattr(main, "get_embedder", lambda: None)
    monkeypatch.setattr(main, "ensure_tables", lambda project_id: ensured.append(project_id))
    monkeypatch.setattr(main, "_warmup_retrieval_path", lambda project_id: warmed.append(project_id))
    monkeypatch.setattr(
        main,
        "maybe_run_memory_maintenance",
        lambda force, project_id: maintained.append(project_id),
    )

    await main.warmup_resources()

    assert ensured == ["default", "proj-active"]
    assert warmed == ["default", "proj-active"]
    assert maintained == ["default"]


@pytest.mark.asyncio
async def test_warmup_resources_marks_warmup_done(monkeypatch):
    main = _load_main()

    monkeypatch.setattr(main, "_warmup_project_ids", lambda: ["default"])
    monkeypatch.setattr(main, "ensure_workspace_scaffold", lambda project_id: None)
    monkeypatch.setattr(main, "get_embedder", lambda: None)
    monkeypatch.setattr(main, "ensure_tables", lambda project_id: None)
    monkeypatch.setattr(main, "_warmup_retrieval_path", lambda project_id: None)
    monkeypatch.setattr(main, "maybe_run_memory_maintenance", lambda force, project_id: None)

    assert warmup_state.is_warmup_done() is False
    await main.warmup_resources()
    assert warmup_state.is_warmup_done() is True


def test_warmup_retrieval_path_warms_knowledge_and_memories(monkeypatch):
    main = _load_main()
    searched_tables: list[str] = []

    class _Route:
        vector = [0.0]
        version = "bge"

    monkeypatch.setattr(
        main,
        "_warmup_retrieval_path",
        main._warmup_retrieval_path,
    )
    import memory.embedder as embedder
    import memory.retrieval as retrieval

    monkeypatch.setattr(
        embedder,
        "encode_query_with_fallback",
        lambda query, project_id="default", table_names=(): _Route(),
    )
    monkeypatch.setattr(
        retrieval,
        "search_records",
        lambda **kwargs: searched_tables.append(kwargs["table_name"]) or [],
    )

    main._warmup_retrieval_path("default")

    assert searched_tables == ["knowledge", "memories"]


def test_warmup_retrieval_path_one_table_failure_does_not_block_other(monkeypatch):
    main = _load_main()
    searched_tables: list[str] = []

    class _Route:
        vector = [0.0]
        version = "bge"

    import memory.embedder as embedder
    import memory.retrieval as retrieval

    def _encode(query, project_id="default", table_names=()):
        if table_names == ("knowledge",):
            raise RuntimeError("knowledge 表尚未 ready")
        return _Route()

    monkeypatch.setattr(embedder, "encode_query_with_fallback", _encode)
    monkeypatch.setattr(
        retrieval,
        "search_records",
        lambda **kwargs: searched_tables.append(kwargs["table_name"]) or [],
    )

    main._warmup_retrieval_path("default")

    assert searched_tables == ["memories"]


def test_readiness_pending_until_warmup_done(monkeypatch):
    import health_payload

    monkeypatch.setattr(
        health_payload,
        "get_db",
        lambda project_id="default": type("_DB", (), {"table_names": lambda self: []})(),
    )

    warmup_state.reset_warmup_state()
    pending = health_payload.build_readiness_payload()
    assert pending["status"] == "not_ready"
    assert pending["warmup"] == "pending"
    assert pending["db"] == "ok"

    warmup_state.mark_warmup_done()
    ready = health_payload.build_readiness_payload()
    assert ready["status"] == "ready"
    assert ready["warmup"] == "done"

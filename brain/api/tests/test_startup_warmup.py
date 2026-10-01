import importlib

import pytest

import warmup_state


def _load_startup():
    return importlib.import_module("startup")


@pytest.fixture(autouse=True)
def _reset_warmup_state():
    warmup_state.reset_warmup_state()
    yield
    warmup_state.reset_warmup_state()


@pytest.fixture(autouse=True)
def _no_gemini_warmup(monkeypatch, request):
    """其他預熱測試不該真的連 Gemini；測台語判斷預熱的測試自己換掉 client。"""
    if "audio_language" not in request.node.name:
        monkeypatch.setattr(_load_startup(), "_warmup_audio_language", lambda: None)


def test_warmup_project_ids_include_projects_with_knowledge_state(monkeypatch):
    startup = _load_startup()

    monkeypatch.setattr(
        startup,
        "list_projects",
        lambda: [
            {"project_id": "default", "document_count": 0, "has_lancedb": False},
            {"project_id": "proj-empty", "document_count": 0, "has_lancedb": False},
            {"project_id": "proj-docs", "document_count": 2, "has_lancedb": False},
            {"project_id": "proj-indexed", "document_count": 0, "has_lancedb": True},
        ],
        raising=False,
    )

    assert startup._warmup_project_ids() == ["default", "proj-docs", "proj-indexed"]


@pytest.mark.asyncio
async def test_warmup_resources_runs_retrieval_warmup_for_each_project(monkeypatch):
    startup = _load_startup()
    ensured: list[str] = []
    warmed: list[str] = []
    maintained: list[str] = []

    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default", "proj-active"])
    monkeypatch.setattr(startup, "ensure_workspace_scaffold", lambda project_id: None)
    monkeypatch.setattr(startup, "get_embedder", lambda: None)
    monkeypatch.setattr(startup, "ensure_tables", lambda project_id: ensured.append(project_id))
    monkeypatch.setattr(startup, "_warmup_retrieval_path", lambda project_id: warmed.append(project_id))
    monkeypatch.setattr(
        startup,
        "maybe_run_memory_maintenance",
        lambda force, project_id: maintained.append(project_id),
    )

    await startup.warmup_resources()

    assert ensured == ["default", "proj-active"]
    assert warmed == ["default", "proj-active"]
    assert maintained == ["default"]


@pytest.mark.asyncio
async def test_warmup_resources_marks_warmup_done(monkeypatch):
    startup = _load_startup()

    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default"])
    monkeypatch.setattr(startup, "ensure_workspace_scaffold", lambda project_id: None)
    monkeypatch.setattr(startup, "get_embedder", lambda: None)
    monkeypatch.setattr(startup, "ensure_tables", lambda project_id: None)
    monkeypatch.setattr(startup, "_warmup_retrieval_path", lambda project_id: None)
    monkeypatch.setattr(startup, "maybe_run_memory_maintenance", lambda force, project_id: None)

    assert warmup_state.is_warmup_done() is False
    await startup.warmup_resources()
    assert warmup_state.is_warmup_done() is True


@pytest.mark.asyncio
async def test_warmup_failure_still_releases_readiness(monkeypatch):
    startup = _load_startup()
    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default"])
    monkeypatch.setattr(startup, "get_embedder", lambda: object())
    monkeypatch.setattr(
        startup,
        "ensure_workspace_scaffold",
        lambda _project_id: (_ for _ in ()).throw(RuntimeError("broken")),
    )

    assert warmup_state.is_warmup_done() is False
    await startup.warmup_resources()
    assert warmup_state.is_warmup_done() is True


def test_warmup_retrieval_path_warms_knowledge_and_memories(monkeypatch):
    startup = _load_startup()
    searched_tables: list[str] = []

    class _Route:
        vector = [0.0]
        version = "bge"

    monkeypatch.setattr(
        startup,
        "_warmup_retrieval_path",
        startup._warmup_retrieval_path,
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

    startup._warmup_retrieval_path("default")

    assert searched_tables == ["knowledge", "memories"]


def test_warmup_retrieval_path_one_table_failure_does_not_block_other(monkeypatch):
    startup = _load_startup()
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

    startup._warmup_retrieval_path("default")

    assert searched_tables == ["memories"]


def test_readiness_pending_until_warmup_done(monkeypatch):
    import health_payload

    monkeypatch.setattr(
        health_payload,
        "get_db",
        lambda project_id="default": type("_DB", (), {"table_names": lambda self: []})(),
    )
    monkeypatch.setattr(
        health_payload,
        "check_embedding_service_readiness",
        lambda: (True, {"status": "ready"}),
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


def _audio_settings(monkeypatch, startup, key="k1"):
    import types

    monkeypatch.setattr(startup, "get_settings", lambda: types.SimpleNamespace(
        gemini_api_key=key, live_audio_language_id_model="gemini-3.5-flash-lite",
    ))


def test_warmup_audio_language_opens_the_shared_client(monkeypatch):
    import types

    import memory.language_detect as language_detect

    startup = _load_startup()
    _audio_settings(monkeypatch, startup)
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(language_detect, "_audio_language_client", lambda key: types.SimpleNamespace(
        models=types.SimpleNamespace(get=lambda model: asked.append((key, model))),
    ))

    startup._warmup_audio_language()

    assert asked == [("k1", "gemini-3.5-flash-lite")]


def test_warmup_audio_language_skips_without_a_key(monkeypatch):
    import memory.language_detect as language_detect

    startup = _load_startup()
    _audio_settings(monkeypatch, startup, key="")
    monkeypatch.setattr(language_detect, "_audio_language_client",
                        lambda key: pytest.fail("no key, no client"))

    startup._warmup_audio_language()


def test_warmup_audio_language_failure_does_not_raise(monkeypatch, caplog):
    import memory.language_detect as language_detect

    startup = _load_startup()
    _audio_settings(monkeypatch, startup)

    def boom(key):
        raise ConnectionError("gemini down")

    monkeypatch.setattr(language_detect, "_audio_language_client", boom)

    startup._warmup_audio_language()

    assert "ConnectionError" in caplog.text


@pytest.mark.asyncio
async def test_audio_language_warmup_runs_before_retrieval_warmup(monkeypatch):
    startup = _load_startup()
    order: list[str] = []
    monkeypatch.setattr(startup, "_warmup_audio_language", lambda: order.append("audio"))
    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default"])
    monkeypatch.setattr(startup, "ensure_workspace_scaffold", lambda project_id: None)
    monkeypatch.setattr(startup, "get_embedder", lambda: order.append("embedder"))
    monkeypatch.setattr(startup, "ensure_tables", lambda project_id: None)
    monkeypatch.setattr(startup, "_warmup_retrieval_path", lambda project_id: None)
    monkeypatch.setattr(startup, "maybe_run_memory_maintenance", lambda force, project_id: None)

    await startup.warmup_resources()

    assert order[:2] == ["audio", "embedder"]

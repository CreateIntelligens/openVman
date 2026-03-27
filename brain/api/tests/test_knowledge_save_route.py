from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _stub_module(name: str, **attrs: object) -> None:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


def _load_main_module():
    sys.modules.pop("main", None)

    _stub_module("config", API_INTERNAL_PORT=8787, get_settings=lambda: SimpleNamespace())
    _stub_module(
        "core.chat_service",
        GenerationContext=type("GenerationContext", (), {}),
        execute_generation=lambda *args, **kwargs: {},
        finalize_generation=lambda *args, **kwargs: {},
        prepare_generation=lambda *args, **kwargs: {},
        record_generation_failure=lambda *args, **kwargs: None,
        stream_generation=lambda *args, **kwargs: iter(()),
    )
    _stub_module("core.slash_command", try_rewrite_slash=lambda *args, **kwargs: None)
    _stub_module(
        "core.sse_events",
        build_exception_protocol_error=lambda *args, **kwargs: {},
        build_protocol_error=lambda *args, **kwargs: {},
        sse_error_to_dict=lambda *args, **kwargs: {},
        sse_event_to_dict=lambda *args, **kwargs: {},
    )
    _stub_module("health_payload", build_health_payload=lambda *args, **kwargs: {})

    from fastapi import APIRouter

    _stub_module("internal_routes", router=APIRouter())
    _stub_module(
        "infra.db",
        ensure_tables=lambda *args, **kwargs: None,
        get_db=lambda *args, **kwargs: SimpleNamespace(create_table=lambda *a, **k: None),
    )
    _stub_module(
        "infra.project_admin",
        create_project=lambda *args, **kwargs: {},
        delete_project=lambda *args, **kwargs: {},
        get_project_info=lambda *args, **kwargs: {},
        list_projects=lambda *args, **kwargs: [],
    )
    _stub_module("knowledge.indexer", rebuild_knowledge_index=lambda *args, **kwargs: {"status": "ok"})
    _stub_module(
        "knowledge.knowledge_admin",
        create_workspace_directory=lambda *args, **kwargs: {},
        delete_workspace_directory=lambda *args, **kwargs: {},
        delete_workspace_document=lambda *args, **kwargs: None,
        list_knowledge_base_directories=lambda *args, **kwargs: [],
        list_knowledge_base_documents=lambda *args, **kwargs: [],
        list_workspace_documents=lambda *args, **kwargs: [],
        move_workspace_document=lambda *args, **kwargs: {},
        read_workspace_document=lambda *args, **kwargs: {},
        save_uploaded_document=lambda *args, **kwargs: {},
        save_workspace_note=lambda *args, **kwargs: {},
        save_workspace_document=lambda *args, **kwargs: {},
        update_workspace_document_meta=lambda *args, **kwargs: {},
    )
    _stub_module(
        "knowledge.workspace",
        ensure_workspace_scaffold=lambda *args, **kwargs: Path("/tmp"),
        parse_identity=lambda *args, **kwargs: {},
    )
    _stub_module(
        "memory.embedder",
        encode_query_with_fallback=lambda *args, **kwargs: {},
        encode_text=lambda *args, **kwargs: [],
        get_embedder=lambda *args, **kwargs: None,
    )
    _stub_module(
        "memory.memory",
        add_memory=lambda *args, **kwargs: {},
        delete_memory=lambda *args, **kwargs: {},
        delete_session_for_project=lambda *args, **kwargs: {},
        list_memories=lambda *args, **kwargs: [],
        list_session_messages=lambda *args, **kwargs: [],
        list_sessions_for_project=lambda *args, **kwargs: [],
    )
    _stub_module(
        "memory.memory_governance",
        maybe_run_memory_maintenance=lambda *args, **kwargs: {"status": "ok"},
    )
    _stub_module("memory.retrieval", search_records=lambda *args, **kwargs: [])
    _stub_module(
        "personas.personas",
        clone_persona_scaffold=lambda *args, **kwargs: {},
        create_persona_scaffold=lambda *args, **kwargs: {},
        delete_persona_scaffold=lambda *args, **kwargs: {},
        list_personas=lambda *args, **kwargs: [],
    )
    _stub_module("protocol.message_envelope", build_message_envelope=lambda *args, **kwargs: {})
    _stub_module(
        "protocol.protocol_events",
        ProtocolValidationError=type("ProtocolValidationError", (Exception,), {}),
        validate_client_event=lambda *args, **kwargs: {},
        validate_server_event=lambda *args, **kwargs: {},
    )
    _stub_module("safety.guardrails", enforce_guardrails=lambda *args, **kwargs: None)
    _stub_module(
        "safety.observability",
        get_metrics_store=lambda: SimpleNamespace(
            increment=lambda *args, **kwargs: None,
            observe=lambda *args, **kwargs: None,
        ),
        log_event=lambda *args, **kwargs: None,
        log_exception=lambda *args, **kwargs: None,
    )
    _stub_module("tools.skill_manager", get_skill_manager=lambda *args, **kwargs: SimpleNamespace())
    _stub_module("tools.tool_registry", get_tool_registry=lambda *args, **kwargs: SimpleNamespace())

    return importlib.import_module("main")


def test_save_knowledge_document_route_schedules_background_reindex(monkeypatch):
    main = _load_main_module()
    scheduled: dict[str, object] = {}

    class FakeAwaitable:
        def __await__(self):
            if False:
                yield
            return None

    def fake_background_reindex(project_id: str):
        scheduled["project_id"] = project_id
        return FakeAwaitable()

    def fake_create_task(task: object):
        scheduled["task"] = task
        return SimpleNamespace()

    monkeypatch.setattr(
        main,
        "save_workspace_document",
        lambda path, content, project_id: {
            "path": path,
            "content": content,
            "project_id": project_id,
        },
    )
    monkeypatch.setattr(main, "_background_reindex", fake_background_reindex)
    monkeypatch.setattr(main.asyncio, "create_task", fake_create_task)

    payload = main.KnowledgeDocumentPutRequest(
        path="knowledge/ingested/example.md",
        content="# Example",
        project_id="default",
    )

    response = asyncio.run(main.save_knowledge_document_route(payload))

    assert response == {
        "status": "ok",
        "document": {
            "path": "knowledge/ingested/example.md",
            "content": "# Example",
            "project_id": "default",
        },
    }
    assert scheduled["project_id"] == "default"
    assert "task" in scheduled

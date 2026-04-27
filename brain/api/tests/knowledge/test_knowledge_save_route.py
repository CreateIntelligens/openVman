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


def _load_knowledge_routes_module():
    sys.modules.pop("routes.knowledge", None)

    _stub_module(
        "core.chat_service",
        record_generation_failure=lambda *args, **kwargs: None,
    )
    _stub_module(
        "knowledge.indexer",
        rebuild_knowledge_index=lambda *args, **kwargs: {"status": "ok"},
        rename_document_records=lambda *args, **kwargs: None,
    )
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
        save_uploaded_artifact=lambda *args, **kwargs: {},
        save_uploaded_document=lambda *args, **kwargs: {},
        save_workspace_note=lambda *args, **kwargs: {},
        save_workspace_document=lambda *args, **kwargs: {},
        update_workspace_document_meta=lambda *args, **kwargs: {},
    )
    _stub_module(
        "safety.observability",
        log_event=lambda *args, **kwargs: None,
        log_exception=lambda *args, **kwargs: None,
        record_circuit_state_change=lambda *args, **kwargs: None,
        record_chain_exhausted=lambda *args, **kwargs: None,
        record_fallback_hop=lambda *args, **kwargs: None,
        record_route_attempt=lambda *args, **kwargs: None,
    )

    return importlib.import_module("routes.knowledge")


def test_save_knowledge_document_route_schedules_background_reindex(monkeypatch):
    knowledge_routes = _load_knowledge_routes_module()
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
        knowledge_routes,
        "save_workspace_document",
        lambda path, content, project_id: {
            "path": path,
            "content": content,
            "project_id": project_id,
        },
    )
    monkeypatch.setattr(knowledge_routes, "_background_reindex", fake_background_reindex)
    monkeypatch.setattr(knowledge_routes.asyncio, "create_task", fake_create_task)

    payload = knowledge_routes.KnowledgeDocumentPutRequest(
        path="knowledge/ingested/example.md",
        content="# Example",
        project_id="default",
    )

    response = asyncio.run(knowledge_routes.save_knowledge_document_route(payload))

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

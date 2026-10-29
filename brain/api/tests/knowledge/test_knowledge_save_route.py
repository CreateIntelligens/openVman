from __future__ import annotations

import asyncio
import importlib
import sys
import types
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile


@pytest.fixture(autouse=True)
def _restore_stubbed_modules():
    """The loader below swaps real modules for stubs; put them back afterwards
    so other test files in the same worker see the real ones."""
    saved = dict(sys.modules)
    yield
    for name in set(sys.modules) - set(saved):
        del sys.modules[name]
    for name, module in saved.items():
        if sys.modules.get(name) is not module:
            sys.modules[name] = module


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
        has_stale_documents=lambda *args, **kwargs: False,
        rebuild_knowledge_index=lambda *args, **kwargs: {"status": "ok"},
        rename_document_records=lambda *args, **kwargs: None,
    )
    _stub_module(
        "knowledge.knowledge_admin",
        apply_workspace_document_normalization=lambda *args, **kwargs: {},
        commit_raw_documents=lambda *args, **kwargs: {"committed": [], "skipped": []},
        create_workspace_directory=lambda *args, **kwargs: {},
        delete_workspace_directory=lambda *args, **kwargs: {},
        delete_workspace_document=lambda *args, **kwargs: None,
        list_knowledge_base_directories=lambda *args, **kwargs: [],
        list_knowledge_base_documents=lambda *args, **kwargs: [],
        list_qa_entries=lambda *args, **kwargs: [],
        list_raw_files=lambda *args, **kwargs: [],
        list_workspace_documents=lambda *args, **kwargs: [],
        move_workspace_document=lambda *args, **kwargs: {},
        preview_workspace_document_normalization=lambda *args, **kwargs: {},
        read_workspace_document=lambda *args, **kwargs: {},
        renormalize_workspace_document=lambda *args, **kwargs: {},
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

    def fakeschedule_reindex(project_id: str):
        scheduled["project_id"] = project_id
        scheduled["task"] = "scheduled"

    monkeypatch.setattr(
        knowledge_routes,
        "save_workspace_document",
        lambda path, content, project_id: {
            "path": path,
            "content": content,
            "project_id": project_id,
        },
    )
    monkeypatch.setattr(knowledge_routes, "schedule_reindex", fakeschedule_reindex)

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


def test_create_note_route_passes_target_dir(monkeypatch):
    knowledge_routes = _load_knowledge_routes_module()
    captured: dict[str, object] = {}

    def fakeschedule_reindex(project_id: str):
        captured["reindex_project_id"] = project_id
        captured["task"] = "scheduled"

    def fake_save_workspace_note(
        title: str,
        content: str,
        project_id: str,
        target_dir: str,
        note_format: str = "text",
    ):
        captured["note"] = {
            "title": title,
            "content": content,
            "project_id": project_id,
            "target_dir": target_dir,
            "note_format": note_format,
        }
        return {"path": "knowledge/faq/FAQ.md", "size": 12}

    monkeypatch.setattr(knowledge_routes, "save_workspace_note", fake_save_workspace_note)
    monkeypatch.setattr(knowledge_routes, "schedule_reindex", fakeschedule_reindex)

    payload = knowledge_routes.KnowledgeNoteCreateRequest(
        title="FAQ",
        content="## Q\n\nA",
        project_id="default",
        target_dir="faq",
    )

    response = asyncio.run(knowledge_routes.create_knowledge_note_route(payload))

    assert captured["note"] == {
        "title": "FAQ",
        "content": "## Q\n\nA",
        "project_id": "default",
        "target_dir": "faq",
        "note_format": "text",
    }
    assert response["path"] == "knowledge/faq/FAQ.md"
    assert captured["reindex_project_id"] == "default"
    assert "task" in captured


# ---------------------------------------------------------------------------
# Upload limits (defence in depth behind the Backend checks)
# ---------------------------------------------------------------------------



class _CountingStream(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.reads = 0

    def read(self, size: int = -1) -> bytes:
        self.reads += 1
        return super().read(size)


def _upload(name: str, data: bytes = b"# hi") -> UploadFile:
    return UploadFile(filename=name, file=_CountingStream(data))


def _saved_calls(monkeypatch, knowledge_routes, attr: str) -> list[tuple]:
    calls: list[tuple] = []
    monkeypatch.setattr(
        knowledge_routes,
        attr,
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"path": "x"},
    )
    monkeypatch.setattr(knowledge_routes, "schedule_reindex", lambda project_id: None)
    return calls


@pytest.mark.parametrize(
    "target_dir",
    ["personas/doctor", "memory", ".learnings", "../raw", "/raw", "raw/../SOUL", "knowledge", "raw\\x"],
)
def test_raw_upload_route_only_writes_under_raw(monkeypatch, target_dir):
    knowledge_routes = _load_knowledge_routes_module()
    calls = _saved_calls(monkeypatch, knowledge_routes, "save_uploaded_artifact")

    with pytest.raises(HTTPException) as caught:
        asyncio.run(knowledge_routes.upload_knowledge_raw_documents_route(
            files=[_upload("a.md")], target_dir=target_dir, project_id="default",
            relative_paths=[],
        ))
    assert caught.value.status_code == 400
    assert calls == []


@pytest.mark.parametrize("target_dir", ["raw", "raw/faq", "raw/faq/sub/"])
def test_raw_upload_route_accepts_raw_subdirectories(monkeypatch, target_dir):
    knowledge_routes = _load_knowledge_routes_module()
    calls = _saved_calls(monkeypatch, knowledge_routes, "save_uploaded_artifact")

    asyncio.run(knowledge_routes.upload_knowledge_raw_documents_route(
        files=[_upload("a.pdf", b"%PDF-1.4")], target_dir=target_dir,
        project_id="default", relative_paths=[],
    ))
    assert calls[0][0][2] == target_dir.rstrip("/")


@pytest.mark.parametrize(("filename", "relative"), [("a.exe", ""), ("a.md", "sub/SOUL.py")])
def test_raw_upload_route_rejects_unlisted_extensions(monkeypatch, filename, relative):
    knowledge_routes = _load_knowledge_routes_module()
    calls = _saved_calls(monkeypatch, knowledge_routes, "save_uploaded_artifact")

    with pytest.raises(HTTPException) as caught:
        asyncio.run(knowledge_routes.upload_knowledge_raw_documents_route(
            files=[_upload(filename)], target_dir="raw", project_id="default",
            relative_paths=[relative] if relative else [],
        ))
    assert caught.value.status_code == 415
    assert calls == []


@pytest.mark.parametrize(
    ("route", "attr", "target_dir"),
    [
        ("upload_knowledge_raw_documents_route", "save_uploaded_artifact", "raw"),
        ("upload_knowledge_documents_route", "save_uploaded_document", "knowledge"),
    ],
)
def test_knowledge_upload_routes_enforce_size_while_reading(monkeypatch, route, attr, target_dir):
    from config import get_settings

    knowledge_routes = _load_knowledge_routes_module()
    calls = _saved_calls(monkeypatch, knowledge_routes, attr)
    monkeypatch.setattr(get_settings(), "knowledge_upload_max_bytes", 2 * 1024 * 1024)
    upload = _upload("big.md", b"x" * (8 * 1024 * 1024))

    with pytest.raises(HTTPException) as caught:
        asyncio.run(getattr(knowledge_routes, route)(
            files=[upload], target_dir=target_dir, project_id="default",
            relative_paths=[],
        ))
    assert caught.value.status_code == 413
    # 1 MB 一塊，第 3 塊就超過 2 MB；剩下的不該再讀。
    assert upload.file.reads <= 3
    assert calls == []


def test_knowledge_upload_route_only_writes_under_knowledge(monkeypatch):
    knowledge_routes = _load_knowledge_routes_module()
    calls = _saved_calls(monkeypatch, knowledge_routes, "save_uploaded_document")

    with pytest.raises(HTTPException) as caught:
        asyncio.run(knowledge_routes.upload_knowledge_documents_route(
            files=[_upload("SOUL.md")], target_dir="knowledge/../", project_id="default",
            relative_paths=[],
        ))
    assert caught.value.status_code == 400
    assert calls == []


def test_brain_knowledge_upload_default_limit():
    from config import BrainSettings

    assert BrainSettings().knowledge_upload_max_bytes == 100 * 1024 * 1024

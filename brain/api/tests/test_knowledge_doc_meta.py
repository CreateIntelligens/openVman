from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _import(module_name: str):
    return importlib.import_module(module_name)


def _configure_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    workspace = _import("knowledge.workspace")
    root = tmp_path / "workspace"
    core_documents = {
        "soul": root / "SOUL.md",
        "agents": root / "AGENTS.md",
        "tools": root / "TOOLS.md",
        "memory": root / "MEMORY.md",
        "identity": root / "IDENTITY.md",
        "learnings": root / ".learnings" / "LEARNINGS.md",
        "errors": root / ".learnings" / "ERRORS.md",
        "memory_summaries": root / "MEMORY_SUMMARIES.md",
    }
    monkeypatch.setattr(workspace, "get_workspace_root", lambda project_id="default": root)
    monkeypatch.setattr(workspace, "get_core_documents", lambda project_id="default": core_documents)
    workspace.ensure_workspace_scaffold()
    return root


def _stub_knowledge_admin_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_indexer = types.ModuleType("knowledge.indexer")
    fake_indexer.load_index_state = lambda project_id="default": {}
    fake_indexer.fingerprint_document = lambda path: "fp"
    monkeypatch.setitem(sys.modules, "knowledge.indexer", fake_indexer)

    fake_personas = types.ModuleType("personas.personas")
    fake_personas.is_persona_core_relative_path = lambda relative_path: False
    monkeypatch.setitem(sys.modules, "personas.personas", fake_personas)


def test_uploaded_document_writes_default_meta(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = _configure_workspace(monkeypatch, tmp_path)
    _stub_knowledge_admin_deps(monkeypatch)
    sys.modules.pop("knowledge.doc_meta", None)
    sys.modules.pop("knowledge.knowledge_admin", None)
    knowledge_admin = _import("knowledge.knowledge_admin")

    document = knowledge_admin.save_uploaded_document(
        "faq.md",
        b"# FAQ\n\nhello world",
        target_dir="knowledge/ingested",
    )

    assert document["path"] == "knowledge/ingested/faq.md"
    assert document["source_type"] == "upload"
    assert document["source_url"] is None
    assert document["enabled"] is True

    meta_path = root / ".doc_meta.json"
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    assert payload["knowledge/ingested/faq.md"]["source_type"] == "upload"
    assert payload["knowledge/ingested/faq.md"]["enabled"] is True


def test_manual_note_writes_manual_meta(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = _configure_workspace(monkeypatch, tmp_path)
    _stub_knowledge_admin_deps(monkeypatch)
    sys.modules.pop("knowledge.doc_meta", None)
    sys.modules.pop("knowledge.knowledge_admin", None)
    knowledge_admin = _import("knowledge.knowledge_admin")

    document = knowledge_admin.save_workspace_note("我的筆記", "這是一段筆記")

    assert document["path"] == "knowledge/notes/我的筆記.md"
    assert document["source_type"] == "manual"
    assert document["enabled"] is True
    assert (root / "knowledge" / "notes" / "我的筆記.md").exists()

    payload = json.loads((root / ".doc_meta.json").read_text(encoding="utf-8"))
    assert payload["knowledge/notes/我的筆記.md"]["source_type"] == "manual"


def test_move_and_delete_document_sync_meta(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = _configure_workspace(monkeypatch, tmp_path)
    _stub_knowledge_admin_deps(monkeypatch)
    sys.modules.pop("knowledge.doc_meta", None)
    sys.modules.pop("knowledge.knowledge_admin", None)
    knowledge_admin = _import("knowledge.knowledge_admin")

    knowledge_admin.save_uploaded_document(
        "faq.md",
        b"# FAQ\n\nhello world",
        target_dir="knowledge/ingested",
    )

    moved = knowledge_admin.move_workspace_document(
        "knowledge/ingested/faq.md",
        "knowledge/notes/faq.md",
    )
    assert moved["path"] == "knowledge/notes/faq.md"

    meta_after_move = json.loads((root / ".doc_meta.json").read_text(encoding="utf-8"))
    assert "knowledge/ingested/faq.md" not in meta_after_move
    assert meta_after_move["knowledge/notes/faq.md"]["source_type"] == "upload"

    knowledge_admin.delete_workspace_document("knowledge/notes/faq.md")
    meta_after_delete = json.loads((root / ".doc_meta.json").read_text(encoding="utf-8"))
    assert "knowledge/notes/faq.md" not in meta_after_delete


def test_document_summary_reads_existing_meta(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = _configure_workspace(monkeypatch, tmp_path)
    _stub_knowledge_admin_deps(monkeypatch)
    sys.modules.pop("knowledge.doc_meta", None)
    sys.modules.pop("knowledge.knowledge_admin", None)
    knowledge_admin = _import("knowledge.knowledge_admin")

    doc_path = root / "knowledge" / "ingested" / "example.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text("# Example\n\nbody", encoding="utf-8")
    (root / ".doc_meta.json").write_text(
        json.dumps(
            {
                "knowledge/ingested/example.md": {
                    "source_type": "web",
                    "source_url": "https://example.com",
                    "enabled": False,
                    "created_at": "2026-03-23T10:00:00",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    documents = knowledge_admin.list_knowledge_base_documents()

    assert len(documents) == 1
    assert documents[0]["source_type"] == "web"
    assert documents[0]["source_url"] == "https://example.com"
    assert documents[0]["enabled"] is False
    assert documents[0]["created_at"] == "2026-03-23T10:00:00"

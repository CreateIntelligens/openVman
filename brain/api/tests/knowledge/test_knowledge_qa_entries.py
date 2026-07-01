from __future__ import annotations

import importlib
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


def _load_knowledge_admin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _configure_workspace(monkeypatch, tmp_path)
    _stub_knowledge_admin_deps(monkeypatch)
    sys.modules.pop("knowledge.doc_meta", None)
    sys.modules.pop("knowledge.knowledge_admin", None)
    return _import("knowledge.knowledge_admin")


def test_list_qa_entries_parses_enabled_qa_documents(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    knowledge_admin = _load_knowledge_admin(monkeypatch, tmp_path)

    knowledge_admin.save_workspace_document(
        "knowledge/faq/general.md",
        "## 什麼是 RAG?\n\n檢索增強生成。\n\n## 怎麼登入?\n\n用 SSO 登入。",
    )
    knowledge_admin.upsert_document_meta("knowledge/faq/general.md", source_type="qa")

    entries = knowledge_admin.list_qa_entries()

    assert entries == [
        {"path": "knowledge/faq/general.md", "question": "什麼是 RAG?", "answer": "檢索增強生成。"},
        {"path": "knowledge/faq/general.md", "question": "怎麼登入?", "answer": "用 SSO 登入。"},
    ]


def test_list_qa_entries_skips_non_qa_and_disabled_documents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    knowledge_admin = _load_knowledge_admin(monkeypatch, tmp_path)

    knowledge_admin.save_workspace_document(
        "knowledge/notes/plain.md",
        "## 這只是一個標題\n\n不是 QA 來源。",
    )

    knowledge_admin.save_workspace_document(
        "knowledge/faq/disabled.md",
        "## 已停用的問題\n\n答案。",
    )
    knowledge_admin.upsert_document_meta(
        "knowledge/faq/disabled.md", source_type="qa", enabled=False
    )

    assert knowledge_admin.list_qa_entries() == []

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
    monkeypatch.setattr(
        workspace,
        "get_core_documents",
        lambda project_id="default": core_documents,
    )
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


def _stub_normalizer(monkeypatch: pytest.MonkeyPatch, cleaned: str) -> None:
    fake_normalizer = types.ModuleType("knowledge.normalizer")
    fake_normalizer.normalize_to_markdown = lambda text: cleaned
    monkeypatch.setitem(sys.modules, "knowledge.normalizer", fake_normalizer)


def test_preview_normalization_does_not_overwrite_document(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    root = _configure_workspace(monkeypatch, tmp_path)
    _stub_knowledge_admin_deps(monkeypatch)
    _stub_normalizer(monkeypatch, "# Clean\n\n整理後內容")
    sys.modules.pop("knowledge.doc_meta", None)
    sys.modules.pop("knowledge.knowledge_admin", None)
    knowledge_admin = _import("knowledge.knowledge_admin")

    doc = root / "knowledge" / "ocr.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# Original\n\n髒 OCR", encoding="utf-8")

    preview = knowledge_admin.preview_workspace_document_normalization("knowledge/ocr.md")

    assert preview["path"] == "knowledge/ocr.md"
    assert preview["content"] == "# Clean\n\n整理後內容"
    assert preview["size"] == len("# Clean\n\n整理後內容".encode("utf-8"))
    assert doc.read_text(encoding="utf-8") == "# Original\n\n髒 OCR"


def test_renormalize_writes_recoverable_backup_before_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    root = _configure_workspace(monkeypatch, tmp_path)
    _stub_knowledge_admin_deps(monkeypatch)
    _stub_normalizer(monkeypatch, "# Clean\n\n整理後內容")
    sys.modules.pop("knowledge.doc_meta", None)
    sys.modules.pop("knowledge.knowledge_admin", None)
    knowledge_admin = _import("knowledge.knowledge_admin")

    doc = root / "knowledge" / "ocr.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# Original\n\n髒 OCR", encoding="utf-8")

    result = knowledge_admin.renormalize_workspace_document("knowledge/ocr.md")

    assert doc.read_text(encoding="utf-8") == "# Clean\n\n整理後內容"
    backup_path = root / result["backup_path"]
    assert backup_path.is_file()
    assert backup_path.read_text(encoding="utf-8") == "# Original\n\n髒 OCR"
    assert backup_path.relative_to(root).as_posix().startswith(".normalization-backups/")


def test_apply_normalization_uses_preview_content_without_calling_llm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    root = _configure_workspace(monkeypatch, tmp_path)
    _stub_knowledge_admin_deps(monkeypatch)

    fake_normalizer = types.ModuleType("knowledge.normalizer")
    fake_normalizer.normalize_to_markdown = lambda text: (_ for _ in ()).throw(
        AssertionError("apply should not call the LLM normalizer")
    )
    monkeypatch.setitem(sys.modules, "knowledge.normalizer", fake_normalizer)
    sys.modules.pop("knowledge.doc_meta", None)
    sys.modules.pop("knowledge.knowledge_admin", None)
    knowledge_admin = _import("knowledge.knowledge_admin")

    doc = root / "knowledge" / "ocr.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# Original\n\n髒 OCR", encoding="utf-8")

    result = knowledge_admin.apply_workspace_document_normalization(
        "knowledge/ocr.md",
        "# Preview Content",
    )

    assert doc.read_text(encoding="utf-8") == "# Preview Content"
    assert (root / result["backup_path"]).read_text(encoding="utf-8") == "# Original\n\n髒 OCR"

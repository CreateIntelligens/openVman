"""Document language detection, persistence and manual override."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    workspace_mod = importlib.import_module("knowledge.workspace")
    root = tmp_path / "workspace"
    (root / "knowledge").mkdir(parents=True)
    monkeypatch.setattr(workspace_mod, "get_workspace_root", lambda project_id="default": root)
    monkeypatch.setattr(workspace_mod, "ensure_workspace_scaffold", lambda project_id="default": root)
    doc_meta = importlib.import_module("knowledge.doc_meta")
    monkeypatch.setattr(doc_meta, "ensure_workspace_scaffold", lambda project_id="default": root)
    return root


def test_detects_once_and_persists(workspace):
    from knowledge import doc_meta

    (workspace / "knowledge" / "catalog.md").write_text("EVAK 沉水泵浦型錄：EUS 系列 0.5~2 HP。", encoding="utf-8")
    (workspace / "knowledge" / "catalog.en.md").write_text(
        "EVAK submersible pump catalog. The EUS series is available from 0.5 to 2 HP.", encoding="utf-8",
    )
    (workspace / "knowledge" / "catalog.es.md").write_text(
        "Catálogo de bombas sumergibles EVAK. La serie EUS está disponible de 0.5 a 2 HP.", encoding="utf-8",
    )
    paths = ["knowledge/catalog.md", "knowledge/catalog.en.md", "knowledge/catalog.es.md"]

    assert doc_meta.resolve_document_languages(paths) == {
        "knowledge/catalog.md": "zh", "knowledge/catalog.en.md": "en", "knowledge/catalog.es.md": "es",
    }
    stored = doc_meta.load_doc_meta()
    assert stored["knowledge/catalog.en.md"]["language_source"] == "auto"

    # 已存的語言不再讀檔：把檔案換成中文也還是 en。
    (workspace / "knowledge" / "catalog.en.md").write_text("中文內容", encoding="utf-8")
    assert doc_meta.resolve_document_languages(["knowledge/catalog.en.md"])["knowledge/catalog.en.md"] == "en"


def test_content_change_redetects_but_manual_sticks(workspace):
    from knowledge import doc_meta

    doc = workspace / "knowledge" / "a.md"
    doc.write_text("This is the English version of the manual.", encoding="utf-8")
    assert doc_meta.resolve_document_languages(["knowledge/a.md"])["knowledge/a.md"] == "en"

    doc.write_text("這是中文版的說明書。", encoding="utf-8")
    doc_meta.touch_document_meta("knowledge/a.md")
    assert doc_meta.resolve_document_languages(["knowledge/a.md"])["knowledge/a.md"] == "zh"

    doc_meta.upsert_document_meta("knowledge/a.md", language="es")
    doc_meta.touch_document_meta("knowledge/a.md")
    entry = doc_meta.get_document_meta("knowledge/a.md")
    assert (entry["language"], entry["language_source"]) == ("es", "manual")

    doc_meta.upsert_document_meta("knowledge/a.md", language=None)
    assert doc_meta.resolve_document_languages(["knowledge/a.md"])["knowledge/a.md"] == "zh"

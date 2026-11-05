"""Document language detection, persistence and manual override."""

from __future__ import annotations

import importlib
import os
import threading
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


def test_failed_save_keeps_the_previous_metadata(workspace, monkeypatch):
    from knowledge import doc_meta

    doc_meta.upsert_document_meta("knowledge/a.md", source_type="qa")
    before = doc_meta.get_doc_meta_path().read_text(encoding="utf-8")

    def _fail(*args, **kwargs):
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", _fail)
        with pytest.raises(OSError):
            doc_meta.upsert_document_meta("knowledge/a.md", source_type="upload")

    assert doc_meta.get_doc_meta_path().read_text(encoding="utf-8") == before
    assert list(workspace.glob(".write-*")) == []


def test_language_detection_keeps_changes_made_while_it_was_reading(workspace, monkeypatch):
    from knowledge import doc_meta
    import memory.language_detect

    (workspace / "knowledge" / "a.md").write_text("內容", encoding="utf-8")

    def _detect_while_an_import_writes(text: str) -> str:
        doc_meta.upsert_document_meta("knowledge/a.md", source_type="qa", origin_path="archive/a.csv")
        return "zh"

    monkeypatch.setattr(memory.language_detect, "detect_document_language", _detect_while_an_import_writes)

    assert doc_meta.resolve_document_languages(["knowledge/a.md"]) == {"knowledge/a.md": "zh"}

    entry = doc_meta.load_doc_meta()["knowledge/a.md"]
    assert entry["source_type"] == "qa"
    assert entry["origin_path"] == "archive/a.csv"
    assert entry["language"] == "zh"


def test_language_set_while_detecting_is_not_overwritten(workspace, monkeypatch):
    from knowledge import doc_meta
    import memory.language_detect

    (workspace / "knowledge" / "a.md").write_text("內容", encoding="utf-8")

    def _detect_while_someone_picks_a_language(text: str) -> str:
        doc_meta.upsert_document_meta("knowledge/a.md", language="es")
        return "zh"

    monkeypatch.setattr(memory.language_detect, "detect_document_language", _detect_while_someone_picks_a_language)

    assert doc_meta.resolve_document_languages(["knowledge/a.md"]) == {"knowledge/a.md": "es"}
    assert doc_meta.get_document_meta("knowledge/a.md")["language_source"] == doc_meta.LANGUAGE_SOURCE_MANUAL


def test_concurrent_writers_keep_each_others_entries(workspace):
    from knowledge import doc_meta

    def _write(prefix: str) -> None:
        for number in range(40):
            doc_meta.upsert_document_meta(f"knowledge/{prefix}_{number}.md", source_type="qa")

    workers = [threading.Thread(target=_write, args=(prefix,)) for prefix in ("a", "b", "c")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert len(doc_meta.load_doc_meta()) == 120

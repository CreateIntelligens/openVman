"""Which documents are disabled is asked on every turn; reparse the metadata only after it changes."""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledge import doc_meta


@pytest.fixture
def meta(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(doc_meta, "get_doc_meta_path", lambda project_id="default": tmp_path / "doc_meta.json")
    doc_meta._disabled_cache.clear()
    yield doc_meta
    doc_meta._disabled_cache.clear()


def test_disabling_a_document_shows_up_on_the_next_read(meta, monkeypatch):
    meta.save_doc_meta({"knowledge/a.md": {"enabled": True}}, "p")
    assert meta.list_disabled_document_paths("p") == set()

    meta.save_doc_meta({"knowledge/a.md": {"enabled": False}}, "p")
    assert meta.list_disabled_document_paths("p") == {"knowledge/a.md"}


def test_unchanged_metadata_is_not_parsed_again(meta, monkeypatch):
    meta.save_doc_meta({"knowledge/a.md": {"enabled": False}}, "p")
    loads = []
    real_load = meta.load_doc_meta
    monkeypatch.setattr(meta, "load_doc_meta", lambda project_id="default": loads.append(1) or real_load(project_id))

    first = meta.list_disabled_document_paths("p")
    first.add("caller mutation")
    assert meta.list_disabled_document_paths("p") == {"knowledge/a.md"}
    assert len(loads) == 1


def test_missing_metadata_means_nothing_disabled(meta):
    assert meta.list_disabled_document_paths("p") == set()

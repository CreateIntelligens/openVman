"""Moving a whole knowledge folder in one step."""

from __future__ import annotations

import json
from pathlib import Path

import knowledge.workspace
import pytest
from knowledge import indexer
from knowledge.doc_meta import load_doc_meta, upsert_document_meta
from knowledge.folder_move import move_knowledge_folder


@pytest.fixture
def workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "workspace"
    monkeypatch.setattr(knowledge.workspace, "get_workspace_root", lambda project_id="default": root)
    knowledge.workspace.ensure_workspace_scaffold()
    products = root / "knowledge" / "products"
    products.mkdir(parents=True)
    for name in ("_catalog.yaml", "A.md", "B.md"):
        (products / name).write_text(name, encoding="utf-8")
    upsert_document_meta("knowledge/products/A.md", "default", enabled=False, language="en")
    upsert_document_meta("knowledge/other.md", "default", language="zh")

    tables: list[list[dict]] = []
    state = {"documents": {"knowledge/products/A.md": "fa", "knowledge/other.md": "fo"}}
    records = [
        {"path": p, "chunk_id": f"{p}::0", "metadata": json.dumps({"path": p, "chunk_id": f"{p}::0"})}
        for p in ("knowledge/products/A.md", "knowledge/other.md")
    ]

    class _Db:
        def create_table(self, _name, data, mode):
            tables.append(data)

    monkeypatch.setattr(indexer, "_load_existing_knowledge_records", lambda _p: records)
    monkeypatch.setattr(indexer, "get_db", lambda _p: _Db())
    monkeypatch.setattr(indexer, "ensure_fts_index", lambda *_a, **_k: None)
    monkeypatch.setattr(indexer, "_load_index_state", lambda _p: state)
    monkeypatch.setattr(indexer, "_save_index_state", lambda docs, _p: state.update(documents=docs))
    return root, tables, state


def test_a_folder_moves_with_its_hidden_files_in_one_index_rebuild(workspace):
    _root, tables, _state = workspace

    renames = move_knowledge_folder("knowledge/products", "knowledge/catalogs/EVAK")

    assert len(renames) == 3
    assert len(tables) == 1


def test_a_folder_can_move_into_its_own_subfolder(workspace):
    root, tables, _state = workspace

    renames = move_knowledge_folder("knowledge/products", "knowledge/products/EVAK沉水泵浦")

    assert renames["knowledge/products/A.md"] == "knowledge/products/EVAK沉水泵浦/A.md"
    assert sorted(p.name for p in (root / "knowledge" / "products").iterdir()) == ["EVAK沉水泵浦"]
    assert (root / "knowledge" / "products" / "EVAK沉水泵浦" / "_catalog.yaml").is_file()
    assert not list((root / "knowledge").glob(".*moving"))
    assert len(tables) == 1


def test_folder_move_keeps_metadata_index_and_chunk_ids(workspace):
    root, tables, state = workspace

    renames = move_knowledge_folder("knowledge/products", "knowledge/catalogs/EVAK")

    assert renames["knowledge/products/_catalog.yaml"] == "knowledge/catalogs/EVAK/_catalog.yaml"
    assert (root / "knowledge" / "catalogs" / "EVAK" / "_catalog.yaml").is_file()
    assert not (root / "knowledge" / "products").exists()
    meta = load_doc_meta("default")
    assert meta["knowledge/catalogs/EVAK/A.md"]["enabled"] is False
    assert meta["knowledge/catalogs/EVAK/A.md"]["language"] == "en"
    assert "knowledge/products/A.md" not in meta
    assert meta["knowledge/other.md"]["language"] == "zh"
    (moved, untouched) = tables[0]
    assert moved["path"] == "knowledge/catalogs/EVAK/A.md"
    assert moved["chunk_id"] == "knowledge/catalogs/EVAK/A.md::0"
    assert json.loads(moved["metadata"])["path"] == "knowledge/catalogs/EVAK/A.md"
    assert untouched["path"] == "knowledge/other.md"
    assert state["documents"] == {"knowledge/catalogs/EVAK/A.md": "fa", "knowledge/other.md": "fo"}


def test_an_existing_target_or_a_folder_outside_knowledge_is_refused(workspace):
    root, _tables, _state = workspace
    (root / "knowledge" / "taken").mkdir()
    with pytest.raises(ValueError, match="已存在"):
        move_knowledge_folder("knowledge/products", "knowledge/taken")
    with pytest.raises(ValueError):
        move_knowledge_folder("knowledge/products", "raw/products")


def test_a_folder_with_quick_qa_documents_is_refused(workspace, monkeypatch):
    from knowledge import qa_nodes

    monkeypatch.setattr(qa_nodes, "referenced_source_paths", lambda _p: {"knowledge/products/B.md"})
    with pytest.raises(ValueError, match="快速問答"):
        move_knowledge_folder("knowledge/products", "knowledge/catalogs/EVAK")

"""The product catalog definition is a system file: not listed, and not deleted silently."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import knowledge.workspace
from knowledge.knowledge_admin import (
    delete_workspace_directory,
    list_knowledge_base_documents,
)
from knowledge.workspace import iter_indexable_documents


@pytest.fixture
def workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    monkeypatch.setattr(knowledge.workspace, "get_workspace_root", lambda project_id="default": root)
    knowledge.workspace.ensure_workspace_scaffold()
    return root


def _write(root: Path, relative: str, text: str = "x") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("folder", ["knowledge/products", "knowledge/products/pumps"])
def test_catalog_definitions_are_not_listed_but_still_indexed(workspace: Path, folder: str):
    _write(workspace, f"{folder}/_catalog.yaml", "title: x\n")
    _write(workspace, f"{folder}/A-1.md", "---\nmodel: A-1\n---\n")

    listed = {doc["path"] for doc in list_knowledge_base_documents("default")}
    indexed = {path.relative_to(workspace).as_posix() for path in iter_indexable_documents("default")}

    assert f"{folder}/A-1.md" in listed
    assert f"{folder}/_catalog.yaml" not in listed
    assert f"{folder}/_catalog.yaml" in indexed


def test_a_catalog_file_elsewhere_is_an_ordinary_document(workspace: Path):
    _write(workspace, "knowledge/notes/_catalog.yaml", "a: b\n")

    assert "knowledge/notes/_catalog.yaml" in {doc["path"] for doc in list_knowledge_base_documents("default")}


@pytest.mark.parametrize("folder", ["knowledge/products", "knowledge/products/pumps"])
def test_a_folder_that_only_looks_empty_says_why_it_cannot_be_deleted(workspace: Path, folder: str):
    _write(workspace, f"{folder}/_catalog.yaml", "title: x\n")

    with pytest.raises(ValueError, match="選型篩選的設定檔"):
        delete_workspace_directory(folder, "default")
    assert (workspace / folder / "_catalog.yaml").exists()


def test_a_folder_with_visible_files_keeps_the_usual_message(workspace: Path):
    _write(workspace, "knowledge/products/_catalog.yaml", "title: x\n")
    _write(workspace, "knowledge/products/A-1.md")

    with pytest.raises(ValueError, match="目錄內仍有檔案"):
        delete_workspace_directory("knowledge/products", "default")

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import knowledge.indexer
import knowledge.workspace
from scripts.migrate_qa_paths import migrate_project_qa_paths


def test_migrate_project_qa_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # 1. 將 get_workspace_root mock 到暫存目錄
    root = tmp_path / "workspace"
    monkeypatch.setattr(knowledge.workspace, "get_workspace_root", lambda project_id="default": root)
    monkeypatch.setattr("scripts.migrate_qa_paths.get_workspace_root", lambda project_id="default": root)

    # 建立必要的 workspace 目錄結構
    knowledge.workspace.ensure_workspace_scaffold()

    # 2. 建立舊的 QA md 檔案 knowledge/test_faq.md
    old_md_path = root / "knowledge" / "test_faq.md"
    old_md_path.parent.mkdir(parents=True, exist_ok=True)
    old_md_path.write_text("# Test FAQ\n\n- Q: Hello?\n- A: World!", encoding="utf-8")

    # 3. 建立舊的 knowledge/.qa_nodes.json，其中有一個 entry 指向 knowledge/test_faq.md
    qa_nodes_path = root / "knowledge" / ".qa_nodes.json"
    qa_nodes_data = {
        "nodes": {
            "node_1": {
                "label": "Test Node",
                "parent_ids": [],
                "child_ids": [],
                "order": 1.0,
                "hidden": False,
                "qa_entries": [
                    {
                        "question": "Hello?",
                        "source_path": "knowledge/test_faq.md",
                        "hidden": False,
                        "image_id": None
                    }
                ]
            }
        }
    }
    with open(qa_nodes_path, "w", encoding="utf-8") as f:
        json.dump(qa_nodes_data, f, ensure_ascii=False, indent=2)

    # 4. 建立舊的 .doc_meta.json，包含 knowledge/test_faq.md（source_type 為 "qa"）
    doc_meta_path = root / ".doc_meta.json"
    doc_meta_data = {
        "knowledge/test_faq.md": {
            "source_type": "qa",
            "enabled": True,
            "created_at": "2026-07-02T10:00:00"
        }
    }
    with open(doc_meta_path, "w", encoding="utf-8") as f:
        json.dump(doc_meta_data, f, ensure_ascii=False, indent=2)

    # Mock indexer functions to trace call and avoid real DB side-effects
    rename_calls = []
    rebuild_calls = []

    monkeypatch.setattr("scripts.migrate_qa_paths.rename_document_records", lambda old, new, project_id="default": rename_calls.append((old, new, project_id)))
    monkeypatch.setattr("scripts.migrate_qa_paths.rebuild_knowledge_index", lambda project_id="default": rebuild_calls.append(project_id))

    # 5. 呼叫 migrate_project_qa_paths
    migrate_project_qa_paths(project_id="default")

    # 6. 驗證
    # - 原本的 knowledge/test_faq.md 不存在，已移動 to knowledge/qa/test_faq.md
    new_md_path = root / "knowledge" / "qa" / "test_faq.md"
    assert not old_md_path.exists()
    assert new_md_path.exists()

    # - .qa_nodes.json 中對應 entry 的 source_path 更新為 knowledge/qa/test_faq.md
    with open(qa_nodes_path, "r", encoding="utf-8") as f:
        updated_qa_nodes = json.load(f)
    assert updated_qa_nodes["nodes"]["node_1"]["qa_entries"][0]["source_path"] == "knowledge/qa/test_faq.md"

    # - .doc_meta.json 中 knowledge/qa/test_faq.md 的 metadata 正確存在且 source_type == "qa"，而舊的路徑已刪除
    with open(doc_meta_path, "r", encoding="utf-8") as f:
        updated_doc_meta = json.load(f)
    assert "knowledge/test_faq.md" not in updated_doc_meta
    assert "knowledge/qa/test_faq.md" in updated_doc_meta
    assert updated_doc_meta["knowledge/qa/test_faq.md"]["source_type"] == "qa"

    # 驗證 mock indexer 呼叫
    assert rename_calls == [("knowledge/test_faq.md", "knowledge/qa/test_faq.md", "default")]
    assert rebuild_calls == ["default"]


def _setup_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    monkeypatch.setattr(knowledge.workspace, "get_workspace_root", lambda project_id="default": root)
    monkeypatch.setattr("scripts.migrate_qa_paths.get_workspace_root", lambda project_id="default": root)
    knowledge.workspace.ensure_workspace_scaffold()
    monkeypatch.setattr("scripts.migrate_qa_paths.rename_document_records", lambda *args, **kwargs: None)
    monkeypatch.setattr("scripts.migrate_qa_paths.rebuild_knowledge_index", lambda project_id="default": None)
    return root


def _write_json(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def test_migrate_downgrades_orphan_qa_docs_without_nodes_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """孤兒 QA 文件（無任何 node 引用、甚至沒有 .qa_nodes.json）應降級為 manual。"""
    root = _setup_workspace(monkeypatch, tmp_path)

    orphan_path = root / "knowledge" / "orphan_faq.md"
    orphan_path.parent.mkdir(parents=True, exist_ok=True)
    orphan_path.write_text("## Q\n\nA", encoding="utf-8")

    doc_meta_path = root / ".doc_meta.json"
    _write_json(doc_meta_path, {
        "knowledge/orphan_faq.md": {"source_type": "qa", "enabled": True},
    })

    migrate_project_qa_paths(project_id="default")

    assert orphan_path.exists()
    with open(doc_meta_path, encoding="utf-8") as f:
        updated = json.load(f)
    assert updated["knowledge/orphan_faq.md"]["source_type"] == "manual"


def test_migrate_handles_referenced_and_orphan_docs_together(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """有引用的搬進 knowledge/qa/，無引用的降級 manual（含已在 qa/ 下的孤兒）。"""
    root = _setup_workspace(monkeypatch, tmp_path)
    knowledge_dir = root / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    referenced = knowledge_dir / "linked_faq.md"
    referenced.write_text("## Q1\n\nA1", encoding="utf-8")
    root_orphan = knowledge_dir / "orphan_faq.md"
    root_orphan.write_text("## Q2\n\nA2", encoding="utf-8")
    qa_orphan = knowledge_dir / "qa" / "stale_faq.md"
    qa_orphan.parent.mkdir(parents=True, exist_ok=True)
    qa_orphan.write_text("## Q3\n\nA3", encoding="utf-8")

    _write_json(knowledge_dir / ".qa_nodes.json", {
        "nodes": {
            "n1": {
                "label": "N1",
                "parent_ids": [],
                "child_ids": [],
                "order": 1.0,
                "hidden": False,
                "qa_entries": [
                    {
                        "question": "Q1",
                        "source_path": "knowledge/linked_faq.md",
                        "hidden": False,
                        "image_id": None,
                    }
                ],
            }
        }
    })
    doc_meta_path = root / ".doc_meta.json"
    _write_json(doc_meta_path, {
        "knowledge/linked_faq.md": {"source_type": "qa", "enabled": True},
        "knowledge/orphan_faq.md": {"source_type": "qa", "enabled": True},
        "knowledge/qa/stale_faq.md": {"source_type": "qa", "enabled": True},
    })

    migrate_project_qa_paths(project_id="default")

    assert not referenced.exists()
    assert (knowledge_dir / "qa" / "linked_faq.md").exists()
    assert root_orphan.exists()
    assert qa_orphan.exists()

    with open(doc_meta_path, encoding="utf-8") as f:
        updated = json.load(f)
    assert updated["knowledge/qa/linked_faq.md"]["source_type"] == "qa"
    assert updated["knowledge/orphan_faq.md"]["source_type"] == "manual"
    assert updated["knowledge/qa/stale_faq.md"]["source_type"] == "manual"

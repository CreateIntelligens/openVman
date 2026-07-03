from __future__ import annotations

import importlib
import os
import sys
import time
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
    monkeypatch.setattr(workspace, "get_workspace_root", lambda project_id="default": root)
    workspace.ensure_workspace_scaffold()
    return root


def test_qa_nodes_crud(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _configure_workspace(monkeypatch, tmp_path)
    qa_nodes = _import("knowledge.qa_nodes")

    # 1. Test create_node
    node = qa_nodes.create_node(
        node_id="node_1",
        label="Node 1",
        parent_ids=[],
        child_ids=[],
        order=1.0,
        hidden=False,
        qa_entries=[
            {
                "question": "What is openVman?",
                "source_path": "knowledge/intro.md",
                "hidden": False,
                "image_id": None
            }
        ]
    )
    assert node["label"] == "Node 1"
    assert node["order"] == 1.0
    assert len(node["qa_entries"]) == 1

    # 2. Test get_node
    retrieved = qa_nodes.get_node("node_1")
    assert retrieved is not None
    assert retrieved["label"] == "Node 1"

    # 3. Test list_nodes
    nodes = qa_nodes.list_nodes()
    assert "node_1" in nodes
    assert len(nodes) == 1

    # 4. Test update_node
    updated = qa_nodes.update_node("node_1", {"label": "Updated Node 1", "order": 1.5})
    assert updated["label"] == "Updated Node 1"
    assert updated["order"] == 1.5

    # 5. Test delete_node
    success = qa_nodes.delete_node("node_1")
    assert success is True
    assert qa_nodes.get_node("node_1") is None
    assert len(qa_nodes.list_nodes()) == 0


def test_qa_nodes_move_and_reorder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _configure_workspace(monkeypatch, tmp_path)
    qa_nodes = _import("knowledge.qa_nodes")

    # Create parent and children
    qa_nodes.create_node("parent_1", "Parent 1")
    qa_nodes.create_node("child_1", "Child 1")
    qa_nodes.create_node("child_2", "Child 2")

    # Move child_1 under parent_1
    qa_nodes.move_node("child_1", ["parent_1"])
    
    parent = qa_nodes.get_node("parent_1")
    child = qa_nodes.get_node("child_1")
    assert "child_1" in parent["child_ids"]
    assert "parent_1" in child["parent_ids"]

    # Reorder test
    # Set orders first
    qa_nodes.update_node("child_1", {"order": 10.0})
    qa_nodes.update_node("child_2", {"order": 20.0})
    
    # Create a new child node in between using sibling_ids_ordered
    # Suppose we have list: ["child_1", "new_child", "child_2"]
    qa_nodes.create_node("new_child", "New Child")
    qa_nodes.reorder_node("new_child", ["child_1", "new_child", "child_2"])
    
    new_c = qa_nodes.get_node("new_child")
    # simplified order: child_1 (1.0), new_child (2.0), child_2 (3.0)
    assert new_c["order"] == 2.0
    assert qa_nodes.get_node("child_1")["order"] == 1.0
    assert qa_nodes.get_node("child_2")["order"] == 3.0


def test_qa_nodes_tree_and_cycle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _configure_workspace(monkeypatch, tmp_path)
    qa_nodes = _import("knowledge.qa_nodes")

    # Create nodes first without linking to avoid dangling reference validation error
    qa_nodes.create_node("node_A", "Node A")
    qa_nodes.create_node("node_B", "Node B")
    qa_nodes.create_node("node_C", "Node C")

    # Link nodes to form cycle: A -> B -> C -> A
    qa_nodes.update_node("node_A", {"child_ids": ["node_B"]})
    qa_nodes.update_node("node_B", {"parent_ids": ["node_A"], "child_ids": ["node_C"]})
    qa_nodes.update_node("node_C", {"parent_ids": ["node_B"], "child_ids": ["node_A"]})

    # Node A is a root node? Node A has parent node_C.
    # To have a valid starting point for get_node_tree, we create a root node that points to node_A.
    qa_nodes.create_node("root_node", "Root Node")
    qa_nodes.update_node("root_node", {"child_ids": ["node_A"]})
    qa_nodes.update_node("node_A", {"parent_ids": ["root_node", "node_C"], "child_ids": ["node_B"]})

    tree = qa_nodes.get_node_tree()
    assert len(tree) == 1
    root_tree = tree[0]
    assert root_tree["node_id"] == "root_node"
    
    # Expand children
    children_a = root_tree["children"]
    assert len(children_a) == 1
    node_a_tree = children_a[0]
    assert node_a_tree["node_id"] == "node_A"

    children_b = node_a_tree["children"]
    assert len(children_b) == 1
    node_b_tree = children_b[0]
    assert node_b_tree["node_id"] == "node_B"

    children_c = node_b_tree["children"]
    assert len(children_c) == 1
    node_c_tree = children_c[0]
    assert node_c_tree["node_id"] == "node_C"

    # node_C points back to node_A, but node_A was already visited,
    # so node_C's children list should NOT recurse into node_A further (or contain empty children, or cycle avoided)
    # Let's verify that node_A is in node_C's children but doesn't have nested children of its own or recursion is cut off.
    children_back = node_c_tree["children"]
    assert len(children_back) == 1
    node_a_back_tree = children_back[0]
    assert node_a_back_tree["node_id"] == "node_A"
    assert len(node_a_back_tree["children"]) == 0


def test_qa_nodes_entries_management(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _configure_workspace(monkeypatch, tmp_path)
    qa_nodes = _import("knowledge.qa_nodes")

    qa_nodes.create_node("node_1", "Node 1")
    qa_nodes.add_qa_entry_to_node("node_1", {
        "question": "Q1",
        "source_path": "knowledge/doc.md",
        "hidden": False,
        "image_id": None
    })

    node = qa_nodes.get_node("node_1")
    assert len(node["qa_entries"]) == 1
    assert node["qa_entries"][0]["question"] == "Q1"

    # Remove QA entry
    qa_nodes.remove_qa_entry_from_node("node_1", "Q1")
    node = qa_nodes.get_node("node_1")
    assert len(node["qa_entries"]) == 0


def test_qa_nodes_duplicate_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _configure_workspace(monkeypatch, tmp_path)
    qa_nodes = _import("knowledge.qa_nodes")

    qa_nodes.create_node("node_1", "Node 1")
    with pytest.raises(ValueError, match="already exists"):
        qa_nodes.create_node("node_1", "Another Node 1")


def test_qa_nodes_dangling_references(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _configure_workspace(monkeypatch, tmp_path)
    qa_nodes = _import("knowledge.qa_nodes")

    with pytest.raises(ValueError, match="Parent node.*does not exist"):
        qa_nodes.create_node("node_1", "Node 1", parent_ids=["non_existent_parent"])

    with pytest.raises(ValueError, match="Child node.*does not exist"):
        qa_nodes.create_node("node_1", "Node 1", child_ids=["non_existent_child"])

    qa_nodes.create_node("node_1", "Node 1")
    with pytest.raises(ValueError, match="Parent node.*does not exist"):
        qa_nodes.update_node("node_1", {"parent_ids": ["non_existent_parent"]})


def test_qa_nodes_qa_duplicate_update(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _configure_workspace(monkeypatch, tmp_path)
    qa_nodes = _import("knowledge.qa_nodes")

    qa_nodes.create_node("node_1", "Node 1")
    qa_nodes.add_qa_entry_to_node("node_1", {
        "question": "Q1",
        "source_path": "path/1.md",
        "hidden": False,
        "image_id": None
    })

    # Add duplicate question with different parameters
    qa_nodes.add_qa_entry_to_node("node_1", {
        "question": "Q1",
        "source_path": "path/2.md",
        "hidden": True,
        "image_id": "img123"
    })

    node = qa_nodes.get_node("node_1")
    assert len(node["qa_entries"]) == 1
    assert node["qa_entries"][0]["source_path"] == "path/2.md"
    assert node["qa_entries"][0]["hidden"] is True
    assert node["qa_entries"][0]["image_id"] == "img123"


def test_qa_nodes_epsilon_rebalance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _configure_workspace(monkeypatch, tmp_path)
    qa_nodes = _import("knowledge.qa_nodes")

    # Create 3 siblings
    qa_nodes.create_node("node_A", "Node A", order=1.0)
    qa_nodes.create_node("node_B", "Node B", order=1.0000000001)
    qa_nodes.create_node("node_C", "Node C", order=2.0)

    # Set orders to be extremely close (< 1e-9 difference)
    qa_nodes.update_node("node_A", {"order": 1.0})
    qa_nodes.update_node("node_C", {"order": 1.0000000005})
    
    # Reordering B should trigger rebalance
    qa_nodes.reorder_node("node_B", ["node_A", "node_B", "node_C"])

    # Verify orders are rebalanced to 1.0, 2.0, 3.0
    assert qa_nodes.get_node("node_A")["order"] == 1.0
    assert qa_nodes.get_node("node_B")["order"] == 2.0
    assert qa_nodes.get_node("node_C")["order"] == 3.0

    # Verify error raised if a sibling doesn't exist
    with pytest.raises(ValueError, match="Sibling node.*does not exist"):
        qa_nodes.reorder_node("node_B", ["node_A", "node_B", "non_existent"])


def test_qa_nodes_corrupted_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = _configure_workspace(monkeypatch, tmp_path)
    qa_nodes = _import("knowledge.qa_nodes")

    # Write corrupted JSON
    nodes_file = root / "knowledge" / ".qa_nodes.json"
    nodes_file.parent.mkdir(parents=True, exist_ok=True)
    with open(nodes_file, "w", encoding="utf-8") as f:
        f.write("{ invalid json")

    # Try listing or getting node, should raise ValueError
    with pytest.raises(ValueError, match="Failed to parse QA nodes file"):
        qa_nodes.list_nodes()


def test_image_cleanup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = _configure_workspace(monkeypatch, tmp_path)
    qa_nodes = _import("knowledge.qa_nodes")

    # 1. 建立節點與 QA 項目，部分項目引用 image_id
    qa_nodes.create_node(
        node_id="node_1",
        label="Node 1",
        qa_entries=[
            {
                "question": "Q1",
                "source_path": "knowledge/doc1.md",
                "hidden": False,
                "image_id": "used_img"
            }
        ]
    )
    qa_nodes.create_node(
        node_id="node_2",
        label="Node 2",
        qa_entries=[
            {
                "question": "Q2",
                "source_path": "knowledge/doc2.md",
                "hidden": False,
                "image_id": "used_img_with_ext.png"
            },
            {
                "question": "Q3",
                "source_path": "knowledge/doc3.md",
                "hidden": False,
                "image_id": None
            }
        ]
    )

    # 2. 建立知識庫的圖片目錄，並寫入測試檔案
    images_dir = root / "knowledge" / ".qa_images"
    images_dir.mkdir(parents=True, exist_ok=True)

    file_used_old = images_dir / "used_img.png"
    file_used_new = images_dir / "used_img_with_ext.png"
    file_unused_old = images_dir / "unused_old.jpg"
    file_unused_recent = images_dir / "unused_recent.png"

    # 建立檔案
    for file_path in [file_used_old, file_used_new, file_unused_old, file_unused_recent]:
        file_path.write_text("test data")

    # 設定修改時間 (st_mtime)
    current_time = time.time()
    old_time = current_time - 700  # 大於 600 秒

    os.utime(file_used_old, (old_time, old_time))
    os.utime(file_unused_old, (old_time, old_time))
    # new 和 recent 的時間維持在當前時間

    # 3. 呼叫清理函式
    deleted_files = qa_nodes.cleanup_unused_images()

    # 4. 驗證回傳的刪除檔案清單（比對檔名或路徑）
    deleted_names = {Path(f).name for f in deleted_files}
    assert "unused_old.jpg" in deleted_names
    assert "unused_recent.png" not in deleted_names
    assert "used_img.png" not in deleted_names
    assert "used_img_with_ext.png" not in deleted_names

    # 5. 驗證檔案是否真的被刪除或保留
    assert file_used_old.exists() is True
    assert file_used_new.exists() is True
    assert file_unused_old.exists() is False
    assert file_unused_recent.exists() is True


def test_add_qa_entries_to_node_batch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _configure_workspace(monkeypatch, tmp_path)
    qa_nodes = _import("knowledge.qa_nodes")

    qa_nodes.create_node("node_1", "Node 1")
    qa_entries = [
        {"question": "Q1", "source_path": "path/1.md", "hidden": False, "image_id": None},
        {"question": "Q2", "source_path": "path/1.md", "hidden": True, "image_id": "img123"},
    ]
    
    qa_nodes.add_qa_entries_to_node("node_1", qa_entries)
    node = qa_nodes.get_node("node_1")
    assert len(node["qa_entries"]) == 2
    assert node["qa_entries"][0]["question"] == "Q1"
    assert node["qa_entries"][1]["question"] == "Q2"
    assert node["qa_entries"][1]["image_id"] == "img123"
    assert node["qa_entries"][1]["hidden"] is True




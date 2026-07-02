from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

# We import app after path setup
from main import app

@pytest.fixture
def client(monkeypatch, tmp_path):
    # Set up mock workspace
    import knowledge.workspace
    import knowledge.indexer
    import memory.embedder
    
    root = tmp_path / "workspace"
    monkeypatch.setattr(knowledge.workspace, "get_workspace_root", lambda project_id="default": root)
    knowledge.workspace.ensure_workspace_scaffold()
    
    # Mock indexer to avoid heavy calculations
    monkeypatch.setattr(knowledge.indexer, "rebuild_knowledge_index", lambda project_id="default": {"status": "ok"})
    
    # Mock embedder to avoid real FlagEmbedding behavior and IndexError
    class FakeEmbedder:
        def encode(self, texts, **kwargs):
            return [[0.1] * 1024 for _ in texts]
    fake_emb = FakeEmbedder()
    
    monkeypatch.setattr(memory.embedder, "get_embedder", lambda *args, **kwargs: fake_emb)
    monkeypatch.setattr(knowledge.indexer, "get_embedder", lambda *args, **kwargs: fake_emb)
    
    # Ensure a clean database for each test (clear cache of qa_nodes)
    sys.modules.pop("knowledge.qa_nodes", None)
    import knowledge.qa_nodes
    
    return TestClient(app)



def test_qa_nodes_crud_routes(client):
    # 1. GET /brain/knowledge/qa/nodes (empty tree)
    response = client.get("/brain/knowledge/qa/nodes")
    assert response.status_code == 200
    assert response.json() == []

    # 2. POST /brain/knowledge/qa/nodes (create node)
    node_payload = {
        "node_id": "test_node_1",
        "label": "Test Node 1",
        "parent_ids": [],
        "child_ids": [],
        "order": 1.0,
        "hidden": False
    }
    response = client.post("/brain/knowledge/qa/nodes", json=node_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["label"] == "Test Node 1"

    # 3. GET /brain/knowledge/qa/nodes (tree with 1 node)
    response = client.get("/brain/knowledge/qa/nodes")
    assert response.status_code == 200
    tree = response.json()
    assert len(tree) == 1
    assert tree[0]["node_id"] == "test_node_1"

    # 4. PATCH /brain/knowledge/qa/nodes/{id} (update node)
    patch_payload = {
        "label": "Updated Test Node 1",
        "hidden": True
    }
    response = client.patch("/brain/knowledge/qa/nodes/test_node_1", json=patch_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["label"] == "Updated Test Node 1"
    assert data["hidden"] is True

    # 5. POST /brain/knowledge/qa/nodes/{id}/move
    # Create another node
    client.post("/brain/knowledge/qa/nodes", json={
        "node_id": "test_node_2",
        "label": "Test Node 2",
        "parent_ids": [],
        "child_ids": [],
        "order": 2.0,
        "hidden": False
    })
    # Move node_1 under node_2
    response = client.post("/brain/knowledge/qa/nodes/test_node_1/move", json={"new_parent_ids": ["test_node_2"]})
    assert response.status_code == 200
    data = response.json()
    assert "test_node_2" in data["parent_ids"]

    # 6. POST /brain/knowledge/qa/nodes/{id}/reorder
    response = client.post("/brain/knowledge/qa/nodes/test_node_1/reorder", json={"sibling_ids_ordered": ["test_node_2", "test_node_1"]})
    assert response.status_code == 200
    data = response.json()
    assert data["order"] == 3.0  # reorder calculation: 2.0 + 1.0 (since it is the last item)

    # 7. DELETE /brain/knowledge/qa/nodes/{id}
    response = client.delete("/brain/knowledge/qa/nodes/test_node_1")
    assert response.status_code == 200
    response = client.delete("/brain/knowledge/qa/nodes/test_node_2")
    assert response.status_code == 200

    # Verification delete
    response = client.get("/brain/knowledge/qa/nodes")
    assert response.json() == []


def test_qa_nodes_merged_and_update_route(client):
    # Create node
    client.post("/brain/knowledge/qa/nodes", json={
        "node_id": "merged_node",
        "label": "Merged Node",
        "parent_ids": [],
        "child_ids": [],
        "order": 1.0,
        "hidden": False
    })

    # Seed one row through the merged editor (creates the source file)
    response = client.put("/brain/knowledge/qa/nodes/merged_node/merged", json=[
        {
            "q": "Q1",
            "a": "A1",
            "img": "img1.png",
            "url": "url1",
            "source_file": "knowledge/qa/manual_merged_node.md",
        }
    ])
    assert response.status_code == 200

    # 1. GET merged view
    response = client.get("/brain/knowledge/qa/nodes/merged_node/merged")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["q"] == "Q1"
    assert items[0]["a"] == "A1"
    assert items[0]["img"] == "img1.png"
    assert items[0]["url"] == "url1"
    assert items[0]["source_file"] == "knowledge/qa/manual_merged_node.md"

    # 2. PUT update merged view
    updated_payload = [
        {
            "q": "Q1-updated",
            "a": "A1-updated",
            "img": "img1-updated.png",
            "url": "url1-updated",
            "source_file": "knowledge/qa/manual_merged_node.md"
        },
        {
            "q": "Q2-new",
            "a": "A2-new",
            "img": "",
            "url": "",
            "source_file": "knowledge/qa/manual_merged_node.md"
        }
    ]
    response = client.put("/brain/knowledge/qa/nodes/merged_node/merged", json=updated_payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # Verify updates
    response = client.get("/brain/knowledge/qa/nodes/merged_node/merged")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    assert items[0]["q"] == "Q1-updated"
    assert items[0]["a"] == "A1-updated"
    assert items[1]["q"] == "Q2-new"


def test_qa_images_routes(client):
    # 1. POST /brain/knowledge/qa/images (upload)
    img_data = b"fake image bytes"
    file_payload = {"file": ("test.png", img_data, "image/png")}
    response = client.post("/brain/knowledge/qa/images", files=file_payload)
    assert response.status_code == 200
    data = response.json()
    assert "image_id" in data
    image_id = data["image_id"]
    assert image_id.endswith(".png")

    # 2. DELETE /brain/knowledge/qa/images/{id}
    response = client.delete(f"/brain/knowledge/qa/images/{image_id}")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # 3. POST /brain/knowledge/qa/images/cleanup-unused
    response = client.post("/brain/knowledge/qa/images/cleanup-unused")
    assert response.status_code == 200
    assert "deleted_files" in response.json()


def test_qa_markdown_code_block_exclusion(client):
    from routes.knowledge_qa import parse_qa_markdown_with_metadata
    from knowledge.knowledge_admin import _parse_qa_markdown

    markdown_with_code = (
        "## Q1\n\n"
        "This is answer 1.\n\n"
        "```python\n"
        "# ## This comment should not be treated as heading\n"
        "print('hello')\n"
        "```\n\n"
        "## Q2\n\n"
        "This is answer 2."
    )

    # 1. Test parse_qa_markdown_with_metadata
    parsed_local = parse_qa_markdown_with_metadata(markdown_with_code)
    assert len(parsed_local) == 2
    assert parsed_local[0]["q"] == "Q1"
    assert "print('hello')" in parsed_local[0]["a"]
    assert "# ## This comment" in parsed_local[0]["a"]
    assert parsed_local[1]["q"] == "Q2"

    # 2. Test _parse_qa_markdown from knowledge_admin
    parsed_admin = _parse_qa_markdown(markdown_with_code, "test.md")
    assert len(parsed_admin) == 2
    assert parsed_admin[0]["question"] == "Q1"
    assert parsed_admin[1]["question"] == "Q2"


def test_attach_and_detach_source(client, tmp_path):
    """掛載 QA 文件登記題目（含 hidden/image_id、去重）；卸載移除該來源的 entries。"""
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    qa_path = root / "knowledge" / "faq_source.md"
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    qa_path.write_text(
        '## Q1\n\nA1\n<!-- qa_metadata: {"img": "p1.png", "url": ""} -->\n\n'
        '## Q2\n\nA2\n<!-- qa_metadata: {"img": "", "url": "", "hidden": true} -->\n',
        encoding="utf-8",
    )
    knowledge.doc_meta.upsert_document_meta("knowledge/faq_source.md", "default", source_type="qa")

    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    qa_nodes.add_qa_entries_to_node("n1", [
        {"question": "Q1", "source_path": "knowledge/other.md", "hidden": False, "image_id": None},
    ])

    response = client.post(
        "/brain/knowledge/qa/nodes/n1/attach-source",
        json={"path": "knowledge/faq_source.md"},
    )
    assert response.status_code == 200
    assert response.json()["added"] == 1  # Q1 已存在，僅 Q2 新增

    node = qa_nodes.get_node("n1")
    entries = {e["question"]: e for e in node["qa_entries"]}
    assert set(entries) == {"Q1", "Q2"}
    assert entries["Q2"]["source_path"] == "knowledge/faq_source.md"
    assert entries["Q2"]["hidden"] is True
    assert entries["Q2"]["image_id"] is None

    response = client.post(
        "/brain/knowledge/qa/nodes/n1/detach-source",
        json={"path": "knowledge/faq_source.md"},
    )
    assert response.status_code == 200
    node = qa_nodes.get_node("n1")
    assert {e["question"] for e in node["qa_entries"]} == {"Q1"}


def test_attach_source_rejects_non_qa_document(client, tmp_path):
    import knowledge.doc_meta

    root = tmp_path / "workspace"
    doc_path = root / "knowledge" / "note.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text("## 不是 QA\n\n內容", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/note.md", "default", source_type="manual")

    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    response = client.post(
        "/brain/knowledge/qa/nodes/n1/attach-source",
        json={"path": "knowledge/note.md"},
    )
    assert response.status_code == 400


def test_documents_list_reports_qa_attached(client, tmp_path):
    """文件清單對 QA 文件回報 qa_attached：被掛載 true、未掛載 false。"""
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    attached = root / "knowledge" / "faq_a.md"
    attached.parent.mkdir(parents=True, exist_ok=True)
    attached.write_text("## Q1\n\nA1\n", encoding="utf-8")
    free = root / "knowledge" / "faq_b.md"
    free.write_text("## Q2\n\nA2\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/faq_a.md", "default", source_type="qa")
    knowledge.doc_meta.upsert_document_meta("knowledge/faq_b.md", "default", source_type="qa")

    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    qa_nodes.add_qa_entries_to_node("n1", [
        {"question": "Q1", "source_path": "knowledge/faq_a.md", "hidden": False, "image_id": None},
    ])

    response = client.get("/brain/knowledge/documents")
    assert response.status_code == 200
    docs = {d["path"]: d for d in response.json()["documents"]}
    assert docs["knowledge/faq_a.md"]["qa_attached"] is True
    assert docs["knowledge/faq_b.md"]["qa_attached"] is False


def test_delete_node_keeps_referenced_qa_docs(client, tmp_path):
    """刪除 node 只解除引用，不刪除底層 QA 文件（文件端擁有內容）。"""
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    doc = root / "knowledge" / "kept.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("## Q1\n\nA1\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/kept.md", "default", source_type="qa")

    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    qa_nodes.add_qa_entries_to_node("n1", [
        {"question": "Q1", "source_path": "knowledge/kept.md", "hidden": False, "image_id": None},
    ])

    response = client.delete("/brain/knowledge/qa/nodes/n1")
    assert response.status_code == 200

    assert doc.exists()
    assert "knowledge/kept.md" in knowledge.doc_meta.load_doc_meta("default")


def test_knowledge_ownership_guard_locks_only_attached_qa_docs(client, tmp_path):
    """guard 僅鎖被 node 掛載的 QA 文件；未掛載者可在文件端自由管理。"""
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    attached = root / "knowledge" / "faq_attached.md"
    attached.parent.mkdir(parents=True, exist_ok=True)
    attached.write_text("## Q1\n\nA1\n", encoding="utf-8")
    detachedoc = root / "knowledge" / "faq_free.md"
    detachedoc.write_text("## Q2\n\nA2\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/faq_attached.md", "default", source_type="qa")
    knowledge.doc_meta.upsert_document_meta("knowledge/faq_free.md", "default", source_type="qa")

    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    qa_nodes.add_qa_entries_to_node("n1", [
        {"question": "Q1", "source_path": "knowledge/faq_attached.md", "hidden": False, "image_id": None},
    ])

    # 已掛載：save / delete / move / renormalize 全部 400
    response = client.put("/brain/knowledge/document", json={
        "path": "knowledge/faq_attached.md",
        "content": "## Q1\n\nUpdated A1\n",
        "project_id": "default",
    })
    assert response.status_code == 400
    assert "已被問答樹掛載" in response.json()["detail"]

    response = client.delete(
        "/brain/knowledge/document", params={"path": "knowledge/faq_attached.md"}
    )
    assert response.status_code == 400

    response = client.post("/brain/knowledge/move", json={
        "source_path": "knowledge/faq_attached.md",
        "target_path": "knowledge/faq_moved.md",
        "project_id": "default",
    })
    assert response.status_code == 400

    response = client.post("/brain/knowledge/renormalize", json={
        "path": "knowledge/faq_attached.md",
        "project_id": "default",
    })
    assert response.status_code == 400

    # 未掛載：可儲存、可移動、可刪除
    response = client.put("/brain/knowledge/document", json={
        "path": "knowledge/faq_free.md",
        "content": "## Q2\n\nUpdated A2\n",
        "project_id": "default",
    })
    assert response.status_code == 200

    response = client.post("/brain/knowledge/move", json={
        "source_path": "knowledge/faq_free.md",
        "target_path": "knowledge/faq_free_moved.md",
        "project_id": "default",
    })
    assert response.status_code == 200

    response = client.delete(
        "/brain/knowledge/document", params={"path": "knowledge/faq_free_moved.md"}
    )
    assert response.status_code == 200


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


def test_qa_nodes_upload_csv_route(client):
    # Create node first
    client.post("/brain/knowledge/qa/nodes", json={
        "node_id": "csv_node",
        "label": "CSV Node",
        "parent_ids": [],
        "child_ids": [],
        "order": 1.0,
        "hidden": False
    })

    # Prepare mock CSV bytes
    csv_content = "q,a,img,url,display\nWhat is Python?,A programming language.,images/python.png,https://python.org,true\nWhat is FastAPI?,A web framework.,,https://fastapi.tiangolo.com,true\n"
    file_payload = {"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")}

    response = client.post("/brain/knowledge/qa/nodes/csv_node/upload-csv", files=file_payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_qa_nodes_manual_route(client):
    # Create node first
    client.post("/brain/knowledge/qa/nodes", json={
        "node_id": "manual_node",
        "label": "Manual Node",
        "parent_ids": [],
        "child_ids": [],
        "order": 1.0,
        "hidden": False
    })

    manual_payload = [
        {"q": "Q1", "a": "A1", "img": "img1.png", "url": "url1"},
        {"q": "Q2", "a": "A2"}
    ]
    response = client.post("/brain/knowledge/qa/nodes/manual_node/manual", json=manual_payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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

    # Add manual QA (creates knowledge/manual_merged_node.md)
    client.post("/brain/knowledge/qa/nodes/merged_node/manual", json=[
        {"q": "Q1", "a": "A1", "img": "img1.png", "url": "url1"}
    ])

    # 1. GET merged view
    response = client.get("/brain/knowledge/qa/nodes/merged_node/merged")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["q"] == "Q1"
    assert items[0]["a"] == "A1"
    assert items[0]["img"] == "img1.png"
    assert items[0]["url"] == "url1"
    assert items[0]["source_file"] == "knowledge/manual_merged_node.md"

    # 2. PUT update merged view
    updated_payload = [
        {
            "q": "Q1-updated",
            "a": "A1-updated",
            "img": "img1-updated.png",
            "url": "url1-updated",
            "source_file": "knowledge/manual_merged_node.md"
        },
        {
            "q": "Q2-new",
            "a": "A2-new",
            "img": "",
            "url": "",
            "source_file": "knowledge/manual_merged_node.md"
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


def test_upload_csv_ghost_entries_cleanup(client):
    # 1. Create node
    client.post("/brain/knowledge/qa/nodes", json={
        "node_id": "ghost_node",
        "label": "Ghost Node",
        "parent_ids": [],
        "child_ids": [],
        "order": 1.0,
        "hidden": False
    })

    # 2. Upload first CSV (with Q1 and Q2)
    csv_1 = "q,a\nQ1,A1\nQ2,A2\n"
    file_payload_1 = {"file": ("test.csv", csv_1.encode("utf-8"), "text/csv")}
    response = client.post("/brain/knowledge/qa/nodes/ghost_node/upload-csv", files=file_payload_1)
    assert response.status_code == 200

    # Verify node has Q1 and Q2
    response = client.get("/brain/knowledge/qa/nodes")
    node = next(n for n in response.json() if n["node_id"] == "ghost_node")
    questions = {e["question"] for e in node["qa_entries"]}
    assert questions == {"Q1", "Q2"}

    # 3. Upload second CSV (re-upload same file, but Q2 is deleted, Q3 is added)
    csv_2 = "q,a\nQ1,A1-updated\nQ3,A3\n"
    file_payload_2 = {"file": ("test.csv", csv_2.encode("utf-8"), "text/csv")}
    response = client.post("/brain/knowledge/qa/nodes/ghost_node/upload-csv", files=file_payload_2)
    assert response.status_code == 200

    # Verify node has Q1 and Q3, and Q2 is cleaned up (no ghost entry)
    response = client.get("/brain/knowledge/qa/nodes")
    node = next(n for n in response.json() if n["node_id"] == "ghost_node")
    questions = {e["question"] for e in node["qa_entries"]}
    assert questions == {"Q1", "Q3"}  # Q2 should be gone


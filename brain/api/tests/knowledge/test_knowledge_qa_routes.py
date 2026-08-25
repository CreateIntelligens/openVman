from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from main import app  # noqa: E402

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

    # QA routes schedule a background reindex instead of running it inline
    import routes.knowledge_qa
    monkeypatch.setattr(routes.knowledge_qa, "schedule_reindex", lambda project_id="default": None)
    
    # Keep route tests independent from the remote embedding gateway.
    class FakeEmbedder:
        def encode(self, texts, **kwargs):
            return [[0.1] * 1024 for _ in texts]
    fake_emb = FakeEmbedder()
    
    monkeypatch.setattr(memory.embedder, "get_embedder", lambda *args, **kwargs: fake_emb)
    monkeypatch.setattr(knowledge.indexer, "get_embedder", lambda *args, **kwargs: fake_emb)
    
    # Ensure a clean database for each test (clear cache of qa_nodes)
    sys.modules.pop("knowledge.qa_nodes", None)
    import knowledge.qa_nodes
    
    from config import get_settings

    return TestClient(
        app,
        headers={"X-Internal-Token": get_settings().gateway_internal_token},
    )



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
    assert data["order"] == 2.0  # simplified sibling ordering: index 1 -> 2.0

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

    # 2. GET /brain/knowledge/qa/images/{id}
    response = client.get(f"/brain/knowledge/qa/images/{image_id}")
    assert response.status_code == 200
    assert response.content == img_data
    assert response.headers["content-type"] == "image/png"

    # 3. DELETE /brain/knowledge/qa/images/{id}
    response = client.delete(f"/brain/knowledge/qa/images/{image_id}")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # 4. POST /brain/knowledge/qa/images/cleanup-unused
    response = client.post("/brain/knowledge/qa/images/cleanup-unused")
    assert response.status_code == 200
    assert "deleted_files" in response.json()


@pytest.mark.parametrize(
    ("suffix", "media_type"),
    [
        ("avif", "image/avif"),
        ("bmp", "image/bmp"),
        ("gif", "image/gif"),
        ("ico", "image/vnd.microsoft.icon"),
        ("jpeg", "image/jpeg"),
        ("jpg", "image/jpeg"),
        ("png", "image/png"),
        ("webp", "image/webp"),
    ],
)
def test_qa_image_routes_support_web_image_formats(client, suffix, media_type):
    image_data = f"fake {suffix} image".encode()
    response = client.post(
        "/brain/knowledge/qa/images",
        files={"file": (f"test.{suffix}", image_data, media_type)},
    )
    assert response.status_code == 200

    image_id = response.json()["image_id"]
    response = client.get(f"/brain/knowledge/qa/images/{image_id}")

    assert response.status_code == 200
    assert response.content == image_data
    assert response.headers["content-type"] == media_type


def test_qa_image_upload_rejects_active_svg_content(client):
    response = client.post(
        "/brain/knowledge/qa/images",
        files={"file": ("unsafe.svg", b"<svg></svg>", "image/svg+xml")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported image type"


def test_qa_image_id_matches_filename_with_spacing(client):
    from knowledge.workspace import resolve_workspace_artifact

    image_path = resolve_workspace_artifact(
        "knowledge/.qa_images/PRP (1).jpg",
        "default",
    )
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"prp image")

    response = client.get("/brain/knowledge/qa/images/PRP(1)")

    assert response.status_code == 200
    assert response.content == b"prp image"
    assert response.headers["content-type"] == "image/jpeg"


def test_merged_route_reads_and_preserves_csv_media(client):
    from knowledge.workspace import ensure_workspace_scaffold
    from knowledge.qa_nodes import update_node

    client.post(
        "/brain/knowledge/qa/nodes",
        json={
            "node_id": "csv_node",
            "label": "CSV Node",
            "parent_ids": [],
            "child_ids": [],
            "order": 1.0,
            "hidden": False,
        },
    )
    source_file = "knowledge/qa/media.csv"
    source_path = ensure_workspace_scaffold() / source_file
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        (
            "index,q,a,img,url,display\n"
            "1,怎麼加入,掃描 QR code,B1-4,https://example.com/line,true\n"
        ),
        encoding="utf-8",
    )
    update_node(
        "csv_node",
        {
            "qa_entries": [
                {
                    "question": "怎麼加入",
                    "source_path": source_file,
                    "hidden": False,
                    "image_id": "B1-4",
                }
            ]
        },
    )

    response = client.get("/brain/knowledge/qa/nodes/csv_node/merged")
    assert response.status_code == 200
    assert response.json()[0] == {
        "index": "1",
        "q": "怎麼加入",
        "a": "掃描 QR code",
        "img": "B1-4",
        "url": "https://example.com/line",
        "source_file": source_file,
        "hidden": False,
    }

    payload = response.json()
    payload[0]["a"] = "請掃描 QR code"
    response = client.put(
        "/brain/knowledge/qa/nodes/csv_node/merged",
        json=payload,
    )
    assert response.status_code == 200

    response = client.get("/brain/knowledge/qa/nodes/csv_node/merged")
    assert response.json()[0]["a"] == "請掃描 QR code"
    assert response.json()[0]["url"] == "https://example.com/line"


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


def test_qa_note_creates_tree_node(client):
    """QA 筆記建立後直接成為問答樹節點（無掛載步驟）。"""
    content = '## Q1\n\nA1\n<!-- qa_metadata: {"img": "", "url": ""} -->'
    response = client.post(
        "/brain/knowledge/note",
        json={"title": "門市問答", "content": content, "note_format": "qa"},
    )
    assert response.status_code == 200
    node_id = response.json()["document"].get("qa_node_id")
    assert node_id

    tree = client.get("/brain/knowledge/qa/nodes").json()
    nodes = {n["node_id"]: n for n in tree}
    assert node_id in nodes
    node = nodes[node_id]
    assert node["label"] == "門市問答"
    assert node["qa_entries"][0]["question"] == "Q1"
    assert node["qa_entries"][0]["source_path"] == "knowledge/qa/門市問答.md"


def test_list_nodes_adopts_orphan_qa_sources(client, tmp_path):
    """讀取問答樹時，未被任何節點引用的 QA 文件會自動補建節點。"""
    import knowledge.doc_meta

    root = tmp_path / "workspace"
    orphan = root / "knowledge" / "qa" / "orphan_faq.md"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("## Q1\n\nA1\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/qa/orphan_faq.md", "default", source_type="qa")

    tree = client.get("/brain/knowledge/qa/nodes").json()
    assert len(tree) == 1
    node = tree[0]
    assert node["label"] == "orphan_faq"
    assert node["qa_entries"][0]["source_path"] == "knowledge/qa/orphan_faq.md"

    # 再次讀取不會重複建節點
    tree_again = client.get("/brain/knowledge/qa/nodes").json()
    assert len(tree_again) == 1


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


def test_ingest_source_merges_rows_and_consumes_doc(client, tmp_path):
    """拖曳進節點：格式 OK 的文件問答列併入節點，原始文件被吸收刪除。"""
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    own = root / "knowledge" / "qa" / "own.md"
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_text('## Q1\n\nA1\n<!-- qa_metadata: {"img": "", "url": ""} -->\n', encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/qa/own.md", "default", source_type="qa")

    dragged = root / "knowledge" / "notes" / "dragged.md"
    dragged.parent.mkdir(parents=True, exist_ok=True)
    dragged.write_text(
        '## Q1\n\n重複的問題\n\n'
        '## Q2\n\nA2\n<!-- qa_metadata: {"img": "", "url": "", "hidden": true} -->\n',
        encoding="utf-8",
    )
    knowledge.doc_meta.upsert_document_meta("knowledge/notes/dragged.md", "default", source_type="manual")

    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    qa_nodes.add_qa_entries_to_node("n1", [
        {"question": "Q1", "source_path": "knowledge/qa/own.md", "hidden": False, "image_id": None},
    ])

    response = client.post(
        "/brain/knowledge/qa/nodes/n1/ingest-source",
        json={"path": "knowledge/notes/dragged.md"},
    )
    assert response.status_code == 200
    assert response.json()["added"] == 1  # Q1 重複被跳過

    node = qa_nodes.get_node("n1")
    entries = {e["question"]: e for e in node["qa_entries"]}
    assert set(entries) == {"Q1", "Q2"}
    assert entries["Q2"]["source_path"] == "knowledge/qa/own.md"
    assert entries["Q2"]["hidden"] is True

    own_content = own.read_text(encoding="utf-8")
    assert "## Q2" in own_content

    assert not dragged.exists()
    assert "knowledge/notes/dragged.md" not in knowledge.doc_meta.load_doc_meta("default")


def test_ingest_source_rejects_nodes_own_doc(client, tmp_path):
    """把節點自己的來源檔拖回自己：不得刪除節點內容。"""
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    own = root / "knowledge" / "qa" / "own.md"
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_text("## Q1\n\nA1\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/qa/own.md", "default", source_type="qa")

    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    qa_nodes.add_qa_entries_to_node("n1", [
        {"question": "Q1", "source_path": "knowledge/qa/own.md", "hidden": False, "image_id": None},
    ])

    response = client.post(
        "/brain/knowledge/qa/nodes/n1/ingest-source",
        json={"path": "knowledge/qa/own.md"},
    )
    assert response.status_code == 400
    assert own.exists()
    node = qa_nodes.get_node("n1")
    assert {e["question"] for e in node["qa_entries"]} == {"Q1"}


def test_ingest_source_clears_dangling_refs_in_other_nodes(client, tmp_path):
    """拖入的文件原屬另一節點：吸收後舊節點的懸空 entries 一併清掉。"""
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    moved = root / "knowledge" / "qa" / "moved.md"
    moved.parent.mkdir(parents=True, exist_ok=True)
    moved.write_text("## Q2\n\nA2\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/qa/moved.md", "default", source_type="qa")

    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    
    # n2 has no children -> should be deleted
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n2", "label": "N2"})
    qa_nodes.add_qa_entries_to_node("n2", [
        {"question": "Q2", "source_path": "knowledge/qa/moved.md", "hidden": False, "image_id": None},
    ])

    # n3 has children -> should not be deleted
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n3", "label": "N3"})
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n3_child", "label": "N3 Child"})
    qa_nodes.move_node("n3_child", ["n3"])
    qa_nodes.add_qa_entries_to_node("n3", [
        {"question": "Q2", "source_path": "knowledge/qa/moved.md", "hidden": False, "image_id": None},
    ])

    response = client.post(
        "/brain/knowledge/qa/nodes/n1/ingest-source",
        json={"path": "knowledge/qa/moved.md"},
    )
    assert response.status_code == 200
    assert response.json()["added"] == 1

    n1 = qa_nodes.get_node("n1")
    assert {e["question"] for e in n1["qa_entries"]} == {"Q2"}
    
    # n2 should be deleted completely
    assert qa_nodes.get_node("n2") is None
    
    # n3 should still exist but have empty qa_entries since it has children
    n3 = qa_nodes.get_node("n3")
    assert n3 is not None
    assert n3["qa_entries"] == []
    
    assert not moved.exists()


def test_ingest_source_rejects_non_qa_format(client, tmp_path):
    import knowledge.doc_meta

    root = tmp_path / "workspace"
    doc = root / "knowledge" / "plain.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("沒有任何標題的純文字內容", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/plain.md", "default", source_type="manual")

    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    response = client.post(
        "/brain/knowledge/qa/nodes/n1/ingest-source",
        json={"path": "knowledge/plain.md"},
    )
    assert response.status_code == 400
    assert doc.exists()


def test_adopt_source_creates_node_from_dropped_doc(client, tmp_path):
    """拖曳到快速問答根目錄：格式 OK 的文件直接成為新節點。"""
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    doc = root / "knowledge" / "notes" / "faq_note.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("## Q1\n\nA1\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/notes/faq_note.md", "default", source_type="manual")

    response = client.post(
        "/brain/knowledge/qa/nodes/adopt-source",
        json={"path": "knowledge/notes/faq_note.md"},
    )
    assert response.status_code == 200
    node_id = response.json()["node_id"]

    node = qa_nodes.get_node(node_id)
    assert node["label"] == "faq_note"
    assert node["qa_entries"][0]["source_path"] == "knowledge/notes/faq_note.md"
    # 收養後文件歸問答樹管理
    meta = knowledge.doc_meta.get_document_meta("knowledge/notes/faq_note.md", "default")
    assert meta.get("source_type") == "qa"

    # 已在樹中的文件不能重複收養
    response = client.post(
        "/brain/knowledge/qa/nodes/adopt-source",
        json={"path": "knowledge/notes/faq_note.md"},
    )
    assert response.status_code == 400


def test_delete_node_removes_owned_qa_doc(client, tmp_path):
    """節點即內容：刪除節點時一併刪除其專屬 QA 文件；仍被其他節點引用者保留。"""
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    owned = root / "knowledge" / "qa" / "owned.md"
    owned.parent.mkdir(parents=True, exist_ok=True)
    owned.write_text("## Q1\n\nA1\n", encoding="utf-8")
    shared = root / "knowledge" / "qa" / "shared.md"
    shared.write_text("## Q2\n\nA2\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/qa/owned.md", "default", source_type="qa")
    knowledge.doc_meta.upsert_document_meta("knowledge/qa/shared.md", "default", source_type="qa")

    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n2", "label": "N2"})
    qa_nodes.add_qa_entries_to_node("n1", [
        {"question": "Q1", "source_path": "knowledge/qa/owned.md", "hidden": False, "image_id": None},
        {"question": "Q2", "source_path": "knowledge/qa/shared.md", "hidden": False, "image_id": None},
    ])
    qa_nodes.add_qa_entries_to_node("n2", [
        {"question": "Q2", "source_path": "knowledge/qa/shared.md", "hidden": False, "image_id": None},
    ])

    response = client.delete("/brain/knowledge/qa/nodes/n1")
    assert response.status_code == 200

    assert not owned.exists()
    assert "knowledge/qa/owned.md" not in knowledge.doc_meta.load_doc_meta("default")
    assert shared.exists()
    assert "knowledge/qa/shared.md" in knowledge.doc_meta.load_doc_meta("default")


def test_knowledge_ownership_guard_locks_only_attached_qa_docs(client, tmp_path):
    """測試直接在文件端刪除或移動 QA 檔案時，系統會自動同步更新問答樹。"""
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

    # 1. 編輯儲存：儲存時會自動將問題內容同步回 JSON 中的 node entries
    response = client.put("/brain/knowledge/document", json={
        "path": "knowledge/faq_attached.md",
        "content": (
            "## Q1 改\n\nUpdated A1\n"
            '<!-- qa_metadata: {"img": "", "url": "", "hidden": true} -->\n'
        ),
        "project_id": "default",
    })
    assert response.status_code == 200
    synced = qa_nodes.get_node("n1")
    assert synced is not None
    entries = synced["qa_entries"]
    assert [e["question"] for e in entries] == ["Q1 改"]
    assert entries[0]["hidden"] is True
    assert entries[0]["source_path"] == "knowledge/faq_attached.md"

    # 2. 移動重新命名：會自動修改 JSON 中對應 entries 的 source_path
    response = client.post("/brain/knowledge/move", json={
        "source_path": "knowledge/faq_attached.md",
        "target_path": "knowledge/faq_attached_moved.md",
        "project_id": "default",
    })
    assert response.status_code == 200
    synced = qa_nodes.get_node("n1")
    assert synced is not None
    assert synced["qa_entries"][0]["source_path"] == "knowledge/faq_attached_moved.md"

    # 3. 刪除檔案：會自動從 JSON 中移除該引用，且若節點變空則自動刪除節點
    response = client.delete(
        "/brain/knowledge/document", params={"path": "knowledge/faq_attached_moved.md"}
    )
    assert response.status_code == 200
    assert qa_nodes.get_node("n1") is None  # 被自動刪除

    # 4. 重新整理：QA 檔案不支援重新整理（LLM 整理會破壞問答格式）
    response = client.post("/brain/knowledge/renormalize", json={
        "path": "knowledge/faq_free.md",
        "project_id": "default",
    })
    assert response.status_code == 400
    assert "不支援重新整理" in response.json()["detail"]


def test_adopt_source_with_parent(client, tmp_path):
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    doc = root / "knowledge" / "notes" / "child_note.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("## Q1\n\nA1\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/notes/child_note.md", "default", source_type="manual")

    # Create a parent node
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "parent_node", "label": "Parent Node"})

    # 1. Adopt with non-existent parent
    response = client.post(
        "/brain/knowledge/qa/nodes/adopt-source",
        json={"path": "knowledge/notes/child_note.md", "parent_id": "non_existent"},
    )
    assert response.status_code == 400
    assert "父節點不存在" in response.json()["detail"]

    # 2. Adopt with valid parent
    response = client.post(
        "/brain/knowledge/qa/nodes/adopt-source",
        json={"path": "knowledge/notes/child_note.md", "parent_id": "parent_node"},
    )
    assert response.status_code == 200
    node_id = response.json()["node_id"]

    node = qa_nodes.get_node(node_id)
    assert node["parent_ids"] == ["parent_node"]


def test_knowledge_move_failure_retains_qa_nodes(client, tmp_path):
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    attached = root / "knowledge" / "faq_to_move.md"
    attached.parent.mkdir(parents=True, exist_ok=True)
    attached.write_text("## Q1\n\nA1\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/faq_to_move.md", "default", source_type="qa")

    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n_move_fail", "label": "Move Fail"})
    qa_nodes.add_qa_entries_to_node("n_move_fail", [
        {"question": "Q1", "source_path": "knowledge/faq_to_move.md", "hidden": False, "image_id": None},
    ])

    response = client.post("/brain/knowledge/move", json={
        "source_path": "knowledge/faq_to_move.md",
        "target_path": "",
        "project_id": "default",
    })
    assert response.status_code == 400
    
    node = qa_nodes.get_node("n_move_fail")
    assert node["qa_entries"][0]["source_path"] == "knowledge/faq_to_move.md"


def test_ingest_source_removes_empty_ghost_node(client, tmp_path):
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    own = root / "knowledge" / "qa" / "own.md"
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_text("## Q1\n\nA1\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/qa/own.md", "default", source_type="qa")

    dragged = root / "knowledge" / "qa" / "ghost.md"
    dragged.write_text("## Q2\n\nA2\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/qa/ghost.md", "default", source_type="qa")

    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n_own", "label": "N Own"})
    qa_nodes.add_qa_entries_to_node("n_own", [
        {"question": "Q1", "source_path": "knowledge/qa/own.md", "hidden": False, "image_id": None},
    ])

    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n_ghost", "label": "N Ghost"})
    qa_nodes.add_qa_entries_to_node("n_ghost", [
        {"question": "Q2", "source_path": "knowledge/qa/ghost.md", "hidden": False, "image_id": None},
    ])

    response = client.post(
        "/brain/knowledge/qa/nodes/n_own/ingest-source",
        json={"path": "knowledge/qa/ghost.md"},
    )
    assert response.status_code == 200

    assert qa_nodes.get_node("n_ghost") is None

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
            return [[0.1] * 768 for _ in texts]
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
    version = items[0]["base_version"]
    response = client.put(
        f"/brain/knowledge/qa/nodes/merged_node/merged?base_version={version}", json=updated_payload,
    )
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


_IMAGE_SAMPLES = {
    "png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02\x08\x02\x00\x00\x00",
    "gif": b"GIF89a\x02\x00\x02\x00\x00\x00\x00;",
    "jpg": b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x02\x00\x02\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9",
    "webp": b"RIFF\x1a\x00\x00\x00WEBPVP8X\x0a\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x01\x00\x00",
    "bmp": b"BM" + b"\x00" * 16 + b"\x02\x00\x00\x00\x02\x00\x00\x00" + b"\x00" * 8,
    "ico": b"\x00\x00\x01\x00\x01\x00" + b"\x00" * 16,
    "avif": b"\x00\x00\x00\x1cftypavif" + b"\x00" * 16,
}
_IMAGE_SAMPLES["jpeg"] = _IMAGE_SAMPLES["jpg"]


@pytest.mark.parametrize("kind, expected", [("qr", {"image_kind": "qr"}), (None, {})])
def test_upload_reports_the_image_kind_only_when_known(client, monkeypatch, kind, expected):
    monkeypatch.setattr("routes.knowledge_qa.qa_image_kind", lambda *_: kind)
    response = client.post(
        "/brain/knowledge/qa/images",
        files={"file": ("test.png", _IMAGE_SAMPLES["png"], "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    data.pop("image_id")
    assert data == expected


def test_qa_images_routes(client):
    # 1. POST /brain/knowledge/qa/images (upload)
    img_data = _IMAGE_SAMPLES["png"]
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
    image_data = _IMAGE_SAMPLES[suffix]
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

    assert response.status_code == 415
    assert response.json()["detail"] == "不支援的圖片格式"


def test_qa_image_upload_rejects_content_that_does_not_match_extension(client):
    response = client.post(
        "/brain/knowledge/qa/images",
        files={"file": ("x.png", _IMAGE_SAMPLES["gif"], "image/png")},
    )
    assert response.status_code == 415


def test_qa_image_upload_without_filename_is_rejected_not_500(client):
    response = client.post(
        "/brain/knowledge/qa/images",
        files={"file": ("", b"\x89PNG", "image/png")},
    )
    assert response.status_code in (415, 422)


def test_qa_image_upload_enforces_size_and_dimensions(client, monkeypatch):
    import struct

    huge = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 9000, 10) + b"\x08\x02\x00\x00\x00"
    response = client.post(
        "/brain/knowledge/qa/images",
        files={"file": ("big.png", huge, "image/png")},
    )
    assert response.status_code == 413
    assert "最長邊" in response.json()["detail"]

    from config import get_settings

    monkeypatch.setattr(get_settings(), "qa_image_max_bytes", 16)
    response = client.post(
        "/brain/knowledge/qa/images",
        files={"file": ("a.png", _IMAGE_SAMPLES["png"] + b"\0" * 32, "image/png")},
    )
    assert response.status_code == 413


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
        "original_q": "怎麼加入",
        "a": "掃描 QR code",
        "img": "B1-4",
        "url": "https://example.com/line",
        "source_file": source_file,
        "hidden": False,
        "base_version": response.json()[0]["base_version"],
        "also_in": [],
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


def test_list_nodes_leaves_unattached_qa_sources_alone(client, tmp_path):
    """沒掛節點的 QA 文件不再自動建節點，否則刪掉的分類會自己長回來。"""
    import knowledge.doc_meta

    root = tmp_path / "workspace"
    orphan = root / "knowledge" / "qa" / "orphan_faq.md"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("## Q1\n\nA1\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/qa/orphan_faq.md", "default", source_type="qa")

    assert client.get("/brain/knowledge/qa/nodes").json() == []
    assert orphan.exists()

    # 要進選單是明確的動作
    response = client.post("/brain/knowledge/qa/nodes/adopt-source", json={"path": "knowledge/qa/orphan_faq.md"})
    assert response.status_code == 200
    assert client.get("/brain/knowledge/qa/nodes").json()[0]["label"] == "orphan_faq"


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
        '## Q1\n\nA1\n\n'
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
    assert response.json()["added"] == 1  # Q1 題目答案都相同，跳過

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

    # 還分給兩個以上的分類時不能併：刪來源會連帶清空它們。
    assert response.status_code == 400
    assert moved.exists()
    assert qa_nodes.get_node("n2") is not None
    assert {e["question"] for e in qa_nodes.get_node("n3")["qa_entries"]} == {"Q2"}

    # 只剩文件自己那個分類時就是搬移，那個分類空了會一起拿掉。
    qa_nodes.update_node("n3", {"qa_entries": []})
    response = client.post(
        "/brain/knowledge/qa/nodes/n1/ingest-source",
        json={"path": "knowledge/qa/moved.md"},
    )
    assert response.status_code == 200
    assert qa_nodes.get_node("n2") is None
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


@pytest.mark.parametrize("new_parent_ids", [["no_such_category"], ["child_of_moved"]])
def test_move_refusal_is_written_for_staff_without_internal_ids(client, new_parent_ids):
    assert client.post("/brain/knowledge/qa/nodes", json={"node_id": "moved", "label": "A"}).status_code == 200
    assert client.post(
        "/brain/knowledge/qa/nodes",
        json={"node_id": "child_of_moved", "label": "B", "parent_ids": ["moved"]},
    ).status_code == 200

    response = client.post("/brain/knowledge/qa/nodes/moved/move", json={"new_parent_ids": new_parent_ids})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "不能移到這裡" in detail
    assert "no_such_category" not in detail
    assert "node" not in detail


def test_missing_category_is_reported_in_plain_words(client):
    response = client.get("/brain/knowledge/qa/nodes/gone/merged")

    assert response.status_code == 404
    assert "找不到這個分類" in response.json()["detail"]


def test_delete_node_keeps_every_qa_doc(client, tmp_path):
    """刪節點只拿掉分類與掛載，文件都留著，仍可被檢索。"""
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

    assert owned.exists()
    assert "knowledge/qa/owned.md" in knowledge.doc_meta.load_doc_meta("default")
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
    assert "上層分類" in response.json()["detail"]

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


_CSV_WITH_INDEX_GAP = (
    "index,q,a,img,url,display,備註\n"
    '1,舊題一,"舊答一,含逗號",a.png,https://x.example/1,true,留著\n'
    "2,舊題二,舊答二,,,false,\n"
    "7,舊題三,舊答三,,,true,也留著\n"
)
_QA_MD = (
    '## 舊題一\n\n舊答一,含逗號\n\n'
    '## 新題\n\n新答\n<!-- qa_metadata: {"img": "b.png", "url": "https://x.example/2", "hidden": true} -->\n'
)


def _write_doc(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _csv_node(client, root: Path, content: str = _CSV_WITH_INDEX_GAP) -> Path:
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    target = _write_doc(root, "knowledge/qa/own.csv", content)
    knowledge.doc_meta.upsert_document_meta("knowledge/qa/own.csv", "default", source_type="qa")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    qa_nodes.update_node("n1", {"qa_entries": qa_nodes._build_entries_for_source("knowledge/qa/own.csv")})
    return target


def test_ingest_markdown_into_csv_node_keeps_existing_rows(client, tmp_path):
    import csv
    import io

    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    target = _csv_node(client, root)
    dragged = _write_doc(root, "knowledge/notes/dragged.md", _QA_MD)

    response = client.post(
        "/brain/knowledge/qa/nodes/n1/ingest-source",
        json={"path": "knowledge/notes/dragged.md"},
    )
    assert response.status_code == 200
    assert response.json()["added"] == 1

    rows = list(csv.DictReader(io.StringIO(target.read_text(encoding="utf-8"))))
    assert [row["index"] for row in rows] == ["1", "2", "7", "8"]
    assert rows[0] == {
        "index": "1", "q": "舊題一", "a": "舊答一,含逗號", "img": "a.png",
        "url": "https://x.example/1", "display": "true", "備註": "留著",
    }
    assert rows[1]["display"] == "false"
    assert rows[2]["備註"] == "也留著"
    assert rows[3] == {
        "index": "8", "q": "新題", "a": "新答", "img": "b.png",
        "url": "https://x.example/2", "display": "false", "備註": "",
    }

    entries = {e["question"]: e for e in qa_nodes.get_node("n1")["qa_entries"]}
    assert set(entries) == {"舊題一", "舊題二", "舊題三", "新題"}
    assert entries["新題"]["source_path"] == "knowledge/qa/own.csv"
    assert entries["新題"]["hidden"] is True
    assert not dragged.exists()


def test_ingest_into_csv_keeps_alias_headers_and_adds_only_needed_columns(client, tmp_path):
    root = tmp_path / "workspace"
    target = _csv_node(client, root, "問題,回答\n舊題,舊答\n")
    _write_doc(
        root, "knowledge/notes/dragged.md",
        '## 新題\n\n新答\n<!-- qa_metadata: {"img": "", "url": "", "hidden": true} -->\n',
    )

    response = client.post(
        "/brain/knowledge/qa/nodes/n1/ingest-source",
        json={"path": "knowledge/notes/dragged.md"},
    )
    assert response.status_code == 200
    assert target.read_text(encoding="utf-8") == "問題,回答,display\n舊題,舊答,\n新題,新答,false\n"


def test_ingest_csv_source_into_markdown_node(client, tmp_path):
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    own = _write_doc(root, "knowledge/qa/own.md", '## Q1\n\nA1\n<!-- qa_metadata: {"img": "", "url": ""} -->\n')
    dragged = _write_doc(root, "knowledge/notes/dragged.csv", "index,q,a,img,url,display\n1,Q2,A2,,,false\n")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    qa_nodes.add_qa_entries_to_node("n1", [
        {"question": "Q1", "source_path": "knowledge/qa/own.md", "hidden": False, "image_id": None},
    ])

    response = client.post(
        "/brain/knowledge/qa/nodes/n1/ingest-source",
        json={"path": "knowledge/notes/dragged.csv"},
    )
    assert response.status_code == 200
    assert response.json()["added"] == 1
    assert "## Q1" in own.read_text(encoding="utf-8")
    assert "## Q2" in own.read_text(encoding="utf-8")
    assert not dragged.exists()


@pytest.mark.parametrize("failing", ["routes.knowledge_qa.save_workspace_document", "os.replace"])
def test_ingest_write_failure_keeps_source_target_and_node(client, tmp_path, monkeypatch, failing):
    import importlib

    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    target = _csv_node(client, root)
    dragged = _write_doc(root, "knowledge/notes/dragged.md", _QA_MD)
    entries_before = qa_nodes.get_node("n1")["qa_entries"]
    target_dir_before = sorted(p.name for p in target.parent.iterdir())

    def boom(*args, **kwargs):
        raise OSError("disk full")

    module_name, attribute = failing.rsplit(".", 1)
    safe_client = TestClient(client.app, raise_server_exceptions=False, headers=dict(client.headers))
    with monkeypatch.context() as patch:
        patch.setattr(importlib.import_module(module_name), attribute, boom)
        response = safe_client.post(
            "/brain/knowledge/qa/nodes/n1/ingest-source",
            json={"path": "knowledge/notes/dragged.md"},
        )

    assert response.status_code == 500
    assert dragged.read_text(encoding="utf-8") == _QA_MD
    assert target.read_text(encoding="utf-8") == _CSV_WITH_INDEX_GAP
    assert qa_nodes.get_node("n1")["qa_entries"] == entries_before
    assert sorted(p.name for p in target.parent.iterdir()) == target_dir_before


def test_ingest_retry_after_node_update_failure_completes(client, tmp_path, monkeypatch):
    """寫完目標、更新節點失敗後重試：題目不重複，節點補齊，來源才刪。"""
    import knowledge.qa_nodes as qa_nodes
    import routes.knowledge_qa

    root = tmp_path / "workspace"
    target = _csv_node(client, root)
    dragged = _write_doc(root, "knowledge/notes/dragged.md", _QA_MD)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    safe_client = TestClient(client.app, raise_server_exceptions=False, headers=dict(client.headers))
    with monkeypatch.context() as patch:
        patch.setattr(routes.knowledge_qa, "update_node", boom)
        failed = safe_client.post(
            "/brain/knowledge/qa/nodes/n1/ingest-source",
            json={"path": "knowledge/notes/dragged.md"},
        )
    assert failed.status_code == 500
    assert dragged.exists()

    retried = client.post(
        "/brain/knowledge/qa/nodes/n1/ingest-source",
        json={"path": "knowledge/notes/dragged.md"},
    )
    assert retried.status_code == 200
    assert retried.json()["added"] == 0
    assert target.read_text(encoding="utf-8").count("新題") == 1
    assert "新題" in {e["question"] for e in qa_nodes.get_node("n1")["qa_entries"]}
    assert not dragged.exists()


@pytest.mark.parametrize(
    ("relative", "content"),
    [
        ("knowledge/qa/own.csv", "foo,bar\n1,2\n"),
        ("knowledge/qa/own.md", "只是一段說明文字，不是問答。\n"),
    ],
)
def test_ingest_refuses_to_overwrite_unreadable_target(client, tmp_path, relative, content):
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    target = _write_doc(root, relative, content)
    dragged = _write_doc(root, "knowledge/notes/dragged.md", _QA_MD)
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    qa_nodes.add_qa_entries_to_node("n1", [
        {"question": "Q", "source_path": relative, "hidden": False, "image_id": None},
    ])

    response = client.post(
        "/brain/knowledge/qa/nodes/n1/ingest-source",
        json={"path": "knowledge/notes/dragged.md"},
    )
    assert response.status_code == 400
    assert target.read_text(encoding="utf-8") == content
    assert dragged.exists()


@pytest.mark.parametrize("content", ["", "index,q,a,img,url,display\n"])
def test_ingest_into_empty_csv_target(client, tmp_path, content):
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    target = _write_doc(root, "knowledge/qa/own.csv", content)
    dragged = _write_doc(root, "knowledge/notes/dragged.md", "## 新題\n\n新答\n")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    qa_nodes.add_qa_entries_to_node("n1", [
        {"question": "Q", "source_path": "knowledge/qa/own.csv", "hidden": False, "image_id": None},
    ])

    response = client.post(
        "/brain/knowledge/qa/nodes/n1/ingest-source",
        json={"path": "knowledge/notes/dragged.md"},
    )
    assert response.status_code == 200
    assert "1,新題,新答" in target.read_text(encoding="utf-8")
    assert not dragged.exists()


def test_adopt_source_accepts_qa_csv(client, tmp_path):
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    target = _write_doc(root, "knowledge/uploads/faq.csv", _CSV_WITH_INDEX_GAP)

    response = client.post(
        "/brain/knowledge/qa/nodes/adopt-source",
        json={"path": "knowledge/uploads/faq.csv"},
    )
    assert response.status_code == 200

    entries = qa_nodes.get_node(response.json()["node_id"])["qa_entries"]
    assert [e["question"] for e in entries] == ["舊題一", "舊題二", "舊題三"]
    assert entries[1]["hidden"] is True
    assert target.read_text(encoding="utf-8") == _CSV_WITH_INDEX_GAP
    meta = knowledge.doc_meta.get_document_meta("knowledge/uploads/faq.csv", "default")
    assert meta["source_type"] == "qa"


def test_adopt_source_rejects_csv_without_qa_columns(client, tmp_path):
    root = tmp_path / "workspace"
    _write_doc(root, "knowledge/uploads/table.csv", "foo,bar\n1,2\n")

    response = client.post(
        "/brain/knowledge/qa/nodes/adopt-source",
        json={"path": "knowledge/uploads/table.csv"},
    )
    assert response.status_code == 400


def _ingest(client, source: str, node_id: str = "n1"):
    return client.post(f"/brain/knowledge/qa/nodes/{node_id}/ingest-source", json={"path": source})


def _node_with_source(client, root: Path, relative: str, content: "str | bytes") -> Path:
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    knowledge.doc_meta.upsert_document_meta(relative, "default", source_type="qa")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "N1"})
    qa_nodes.update_node("n1", {"qa_entries": [
        {"question": "佔位", "source_path": relative, "hidden": False, "image_id": None},
    ]})
    return target


@pytest.mark.parametrize("alias", ["./knowledge/qa/own.md", "knowledge/qa/../qa/own.md", "knowledge//qa/own.md"])
def test_ingest_refuses_own_source_under_another_spelling(client, tmp_path, alias):
    root = tmp_path / "workspace"
    target = _node_with_source(client, root, "knowledge/qa/own.md", _QA_MD)

    assert _ingest(client, alias).status_code == 400
    assert target.read_text(encoding="utf-8") == _QA_MD


@pytest.mark.parametrize(
    "source",
    ["q,a\nQ,答一\nQ,答二\n", "q,a\n,無題答甲\n,無題答乙\n"],
)
def test_ingest_refuses_source_with_conflicting_duplicates(client, tmp_path, source):
    root = tmp_path / "workspace"
    target = _node_with_source(client, root, "knowledge/qa/own.csv", "q,a\n舊,舊答\n")
    dragged = _write_doc(root, "knowledge/notes/d.csv", source)

    assert _ingest(client, "knowledge/notes/d.csv").status_code == 400
    assert target.read_text(encoding="utf-8") == "q,a\n舊,舊答\n"
    assert dragged.read_text(encoding="utf-8") == source


@pytest.mark.parametrize(
    "source",
    ['q,a\nQ2,"前段\n## 注意事項\n後段"\n', 'q,a\n"第一行\n第二行",A2\n'],
)
def test_ingest_refuses_csv_content_markdown_cannot_hold(client, tmp_path, source):
    root = tmp_path / "workspace"
    target = _node_with_source(client, root, "knowledge/qa/own.md", _QA_MD)
    dragged = _write_doc(root, "knowledge/notes/d.csv", source)

    assert _ingest(client, "knowledge/notes/d.csv").status_code == 400
    assert target.read_text(encoding="utf-8") == _QA_MD
    assert dragged.exists()


def test_ingest_keeps_markdown_text_before_the_first_question(client, tmp_path):
    root = tmp_path / "workspace"
    original = "# 標題\n\n前言\n\n## Q1\n\nA1\n"
    target = _node_with_source(client, root, "knowledge/qa/own.md", original)
    _write_doc(root, "knowledge/notes/d.md", "## Q2\n\nA2\n")

    assert _ingest(client, "knowledge/notes/d.md").status_code == 200
    content = target.read_text(encoding="utf-8")
    assert content.startswith(original.rstrip())
    assert "## Q2" in content


@pytest.mark.parametrize(
    "content",
    [
        "q,a\n舊,答案前段,答案後段\n",  # 多出來的格會被新增的 img 欄當成圖片
        "q,a,a\n舊,甲,乙\n",  # 重複欄位：新列寫前一欄，讀的卻是後一欄
    ],
)
def test_ingest_refuses_csv_it_cannot_extend_faithfully(client, tmp_path, content):
    root = tmp_path / "workspace"
    target = _node_with_source(client, root, "knowledge/qa/own.csv", content)
    dragged = _write_doc(
        root, "knowledge/notes/d.md",
        '## 新\n\n新答\n<!-- qa_metadata: {"img": "b.png", "url": ""} -->\n',
    )

    assert _ingest(client, "knowledge/notes/d.md").status_code == 400
    assert target.read_text(encoding="utf-8") == content
    assert dragged.exists()


def test_ingest_refuses_non_utf8_target_and_source(client, tmp_path):
    root = tmp_path / "workspace"
    gbk_target = "q,a\n旧题怎么办,旧答\n".encode("gbk")
    target = _node_with_source(client, root, "knowledge/qa/own.csv", gbk_target)
    dragged = _write_doc(root, "knowledge/notes/d.md", "## 新\n\n新答\n")
    assert _ingest(client, "knowledge/notes/d.md").status_code == 400
    assert target.read_bytes() == gbk_target
    assert dragged.exists()

    gbk_source = "q,a\n来源题怎么办,来源答\n".encode("gbk")
    source = root / "knowledge" / "notes" / "s.csv"
    source.write_bytes(gbk_source)
    adopted = client.post("/brain/knowledge/qa/nodes/adopt-source", json={"path": "knowledge/notes/s.csv"})
    assert adopted.status_code == 400
    assert source.read_bytes() == gbk_source


def test_ingest_uses_target_file_values_for_question_missing_from_node(client, tmp_path):
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    _node_with_source(client, root, "knowledge/qa/own.csv", "q,a,img,display\n舊,舊答,keep.png,false\n")
    _write_doc(root, "knowledge/notes/d.md", '## 舊\n\n舊答\n<!-- qa_metadata: {"img": "keep.png"} -->')

    assert _ingest(client, "knowledge/notes/d.md").status_code == 200
    entry = next(e for e in qa_nodes.get_node("n1")["qa_entries"] if e["question"] == "舊")
    assert entry["hidden"] is True
    assert entry["image_id"] == "keep.png"


@pytest.mark.parametrize("index", ["NaN", "-inf", "1.5", "abc", ""])
def test_ingest_into_csv_tolerates_unusual_index(client, tmp_path, index):
    root = tmp_path / "workspace"
    target = _node_with_source(client, root, "knowledge/qa/own.csv", f"index,q,a\n{index},舊,舊答\n")
    _write_doc(root, "knowledge/notes/d.md", "## 新\n\n新答\n")

    assert _ingest(client, "knowledge/notes/d.md").status_code == 200
    assert "舊,舊答" in target.read_text(encoding="utf-8")
    assert "新,新答" in target.read_text(encoding="utf-8")


def test_concurrent_ingests_keep_every_question(client, tmp_path, monkeypatch):
    import threading

    import knowledge.qa_nodes as qa_nodes
    import routes.knowledge_qa

    root = tmp_path / "workspace"
    target = _node_with_source(client, root, "knowledge/qa/own.csv", "q,a\n舊,舊答\n")
    _write_doc(root, "knowledge/notes/a.md", "## 甲\n\n甲答\n")
    _write_doc(root, "knowledge/notes/b.md", "## 乙\n\n乙答\n")

    # 讓兩個請求都讀完目標才寫；有鎖時另一個等不到，逾時後照常往下。
    barrier = threading.Barrier(2)
    real_save = routes.knowledge_qa.save_workspace_document

    def rendezvous_save(*args, **kwargs):
        try:
            barrier.wait(timeout=1)
        except threading.BrokenBarrierError:
            pass
        return real_save(*args, **kwargs)

    monkeypatch.setattr(routes.knowledge_qa, "save_workspace_document", rendezvous_save)
    results: list[int] = []
    threads = [
        threading.Thread(target=lambda s=s: results.append(_ingest(client, s).status_code))
        for s in ("knowledge/notes/a.md", "knowledge/notes/b.md")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [200, 200]
    content = target.read_text(encoding="utf-8")
    assert "甲,甲答" in content and "乙,乙答" in content
    assert {"甲", "乙"} <= {e["question"] for e in qa_nodes.get_node("n1")["qa_entries"]}


def test_adopted_csv_keeps_one_entry_per_row(client, tmp_path):
    """答案裡的 ## 行與多行題目不能在建節點時變成別的題目。"""
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    _write_doc(
        root, "knowledge/uploads/faq.csv",
        'q,a\nQ1,"前段\n## 注意事項\n後段"\n"第一行\n第二行",A2\n',
    )

    response = client.post("/brain/knowledge/qa/nodes/adopt-source", json={"path": "knowledge/uploads/faq.csv"})
    assert response.status_code == 200
    node_id = response.json()["node_id"]
    assert [e["question"] for e in qa_nodes.get_node(node_id)["qa_entries"]] == ["Q1", "第一行\n第二行"]

    merged = client.get(f"/brain/knowledge/qa/nodes/{node_id}/merged").json()
    assert merged[0]["a"] == "前段\n## 注意事項\n後段"
    assert merged[1]["a"] == "A2"


def test_saving_a_document_handles_long_names_and_keeps_mode(client, tmp_path):
    import os

    root = tmp_path / "workspace"
    name = "長" * 80 + ".md"
    assert len(name.encode()) > 240
    relative = f"knowledge/{name}"
    path = _write_doc(root, relative, "舊內容\n")
    os.chmod(path, 0o640)

    response = client.put("/brain/knowledge/document", json={"path": relative, "content": "新內容\n"})
    assert response.status_code == 200

    assert path.read_text(encoding="utf-8") == "新內容\n"
    assert (path.stat().st_mode & 0o777) == 0o640
    assert [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")] == []


@pytest.mark.parametrize(
    ("relative", "target_content"),
    [
        ("knowledge/qa/own.csv", "q,a\n甲,甲答\n乙,乙答\n丙,丙答\n"),
        ("knowledge/qa/own.md", "## 甲\n\n甲答\n\n## 乙\n\n乙答\n\n## 丙\n\n丙答\n"),
    ],
)
def test_ingest_reports_every_conflicting_answer_and_changes_nothing(client, tmp_path, relative, target_content):
    import knowledge.qa_nodes as qa_nodes

    root = tmp_path / "workspace"
    target = _node_with_source(client, root, relative, target_content)
    source = "## 甲\n\n不同的甲答\n\n## 乙\n\n乙答\n\n## 丙\n\n不同的丙答\n\n## 丁\n\n丁答\n"
    dragged = _write_doc(root, "knowledge/notes/d.md", source)
    entries_before = qa_nodes.get_node("n1")["qa_entries"]

    response = _ingest(client, "knowledge/notes/d.md")

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "甲" in detail and "丙" in detail
    assert "乙" not in detail and "丁" not in detail  # 只列衝突的題目
    assert target.read_text(encoding="utf-8") == target_content
    assert dragged.read_text(encoding="utf-8") == source
    assert qa_nodes.get_node("n1")["qa_entries"] == entries_before


def test_ingest_ignores_surrounding_whitespace_when_comparing_answers(client, tmp_path):
    root = tmp_path / "workspace"
    target = _node_with_source(client, root, "knowledge/qa/own.csv", 'q,a\n舊, 舊答 \n')
    dragged = _write_doc(root, "knowledge/notes/d.md", "##  舊 \n\n舊答\n\n## 新\n\n新答\n")

    response = _ingest(client, "knowledge/notes/d.md")

    assert response.status_code == 200
    assert response.json()["added"] == 1
    assert "新,新答" in target.read_text(encoding="utf-8")
    assert not dragged.exists()


def test_ingest_lists_every_conflict_inside_the_source(client, tmp_path):
    root = tmp_path / "workspace"
    _node_with_source(client, root, "knowledge/qa/own.csv", "q,a\n舊,舊答\n")
    _write_doc(root, "knowledge/notes/d.csv", "q,a\n甲,一\n甲,二\n乙,三\n乙,四\n丙,五\n")

    response = _ingest(client, "knowledge/notes/d.csv")

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "甲" in detail and "乙" in detail and "丙" not in detail


def test_the_all_questions_route_lists_every_question(client):
    resp = client.post(
        "/brain/knowledge/qa/nodes",
        json={"node_id": "faq", "label": "常見問題"},
    )
    assert resp.status_code == 200
    assert client.post("/brain/knowledge/qa/nodes/faq/entries", json={"question": "選單題"}).status_code == 200

    resp = client.get("/brain/knowledge/qa/questions", params={"project_id": "default"})

    assert resp.status_code == 200
    body = resp.json()
    assert [category["label"] for category in body["categories"]] == ["常見問題"]
    assert [row["question"] for row in body["questions"]] == ["選單題"]
    assert body["questions"][0]["source"]["kind"] == "menu_only"

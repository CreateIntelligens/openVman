"""Regression cases from the independent review of the quick-QA tree.

每一條都是實際重現過的問題，斷言寫預期行為。
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

# 模組載入時就綁定：別的測試會 reload knowledge_admin，晚綁會拿到指著別的暫存目錄的版本。
from main import app  # noqa: E402
from scripts import label_qa_languages  # noqa: E402

BASE = "/brain/knowledge/qa"
SHARED = "knowledge/qa/shared.csv"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("GATEWAY_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setenv("NO_ANSWER_JUDGE_ENABLED", "false")
    monkeypatch.setattr("config._settings", None)
    from config import get_settings

    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    data_root = tmp_path / "data" / "projects"
    data_root.mkdir(parents=True, exist_ok=True)
    import infra.project_context as pc

    monkeypatch.setattr(pc, "_DATA_ROOT", data_root)
    import knowledge.workspace as kw

    if hasattr(kw, "_CORE_CONTEXT_CACHE"):
        kw._CORE_CONTEXT_CACHE.clear()


@pytest.fixture
def workspace(monkeypatch, tmp_path) -> Path:
    import knowledge.indexer
    import knowledge.workspace
    import memory.embedder
    import routes.knowledge
    import routes.knowledge_qa

    root = tmp_path / "workspace"
    monkeypatch.setattr(knowledge.workspace, "get_workspace_root", lambda project_id="default": root)
    knowledge.workspace.ensure_workspace_scaffold()
    monkeypatch.setattr(knowledge.indexer, "rebuild_knowledge_index", lambda project_id="default": {"status": "ok"})
    monkeypatch.setattr(routes.knowledge_qa, "schedule_reindex", lambda project_id="default": None)
    monkeypatch.setattr(routes.knowledge, "schedule_reindex", lambda project_id="default": None)
    monkeypatch.setattr(routes.knowledge, "rename_document_records", lambda *a, **k: None, raising=False)

    class FakeEmbedder:
        def encode(self, texts, **kwargs):
            return [[0.1] * 768 for _ in texts]

    monkeypatch.setattr(memory.embedder, "get_embedder", lambda *a, **k: FakeEmbedder())
    return root


def _make_client(raise_errors: bool = True) -> TestClient:
    from config import get_settings

    return TestClient(
        app,
        raise_server_exceptions=raise_errors,
        headers={"X-Internal-Token": get_settings().gateway_internal_token},
    )


@pytest.fixture
def client(workspace) -> TestClient:
    return _make_client()


@pytest.fixture
def loose(workspace) -> TestClient:
    """A client that sees a 500 instead of the exception."""
    return _make_client(raise_errors=False)


def write_doc(root: Path, relative: str, content, source_type: str = "qa") -> Path:
    import knowledge.doc_meta

    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    knowledge.doc_meta.upsert_document_meta(relative, "default", source_type=source_type)
    return path


def entry(question: str, source: str = SHARED, hidden: bool = False, image_id: str | None = None) -> dict:
    return {"question": question, "source_path": source, "hidden": hidden, "image_id": image_id}


def make_node(client: TestClient, node_id: str, entries: list[dict]) -> None:
    from knowledge import qa_nodes

    assert client.post(f"{BASE}/nodes", json={"node_id": node_id, "label": node_id}).status_code == 200
    qa_nodes.update_node(node_id, {"qa_entries": entries})


def merged(client: TestClient, node_id: str) -> list[dict]:
    response = client.get(f"{BASE}/nodes/{node_id}/merged")
    assert response.status_code == 200, response.text
    return response.json()


def pane(rows: list[dict]) -> list[dict]:
    """MergedCsvPane.handleSave：index 照畫面重編，其他欄位（含 base_version、original_q）原樣送回。"""
    return [{**row, "index": str(position)} for position, row in enumerate(rows, start=1)]


def put(client: TestClient, node_id: str, rows: list[dict]):
    return client.put(f"{BASE}/nodes/{node_id}/merged", json=rows)


def new_row(q: str, a: str, source: str = SHARED) -> dict:
    """MergedCsvPane.handleAddRow 建出來的新列：沒有 base_version、original_q，圖片連結空白。"""
    return {"q": q, "a": a, "img": "", "url": "", "source_file": source, "hidden": False}


def table(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(path.read_bytes().decode("utf-8-sig"))))


def by_q(path: Path) -> dict[str, dict[str, str]]:
    return {row["q"]: row for row in table(path)}


def questions(node_id: str) -> list[str]:
    from knowledge import qa_nodes

    return [item["question"] for item in qa_nodes.get_node(node_id)["qa_entries"]]


def during_write(monkeypatch, request_fn) -> dict:
    """Send ``request_fn`` after PUT /merged planned its write and before it writes.

    The request runs on its own thread: a route that takes the shared lock just waits and
    finishes after the PUT, a route that does not take it gets in between.
    """
    import knowledge.qa_merged as qa_merged

    real = qa_merged._write_all
    state: dict = {"thread": None, "status": None, "finished_inside": None}

    def wrapped(plans, project_id, then):
        def _send():
            state["status"] = request_fn()

        thread = threading.Thread(target=_send, daemon=True)
        state["thread"] = thread
        thread.start()
        thread.join(1.5)
        state["finished_inside"] = not thread.is_alive()
        return real(plans, project_id, then)

    monkeypatch.setattr(qa_merged, "_write_all", wrapped)
    return state


TWO_ROWS = "index,q,a\n1,甲,甲答\n2,乙,乙答\n"






# ---------- 資料遺失：畫面走得到 ----------


def test_a1a_stale_editor_clearing_all_rows_gets_409(client, workspace):
    doc = write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n", [entry("甲"), entry("乙")])
    merged(client, "n")  # A 分頁載入甲乙
    tab_b = merged(client, "n")
    assert put(client, "n", pane([*tab_b, new_row("戊", "戊答")])).status_code == 200  # B 分頁新增戊
    response = put(client, "n", [])  # A 分頁把看到的兩列刪掉後存檔
    assert response.status_code == 409
    assert "戊" in by_q(doc)


def test_a1b_stale_editor_replacing_all_rows_gets_409(client, workspace):
    doc = write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n", [entry("甲"), entry("乙")])
    merged(client, "n")
    tab_b = merged(client, "n")
    assert put(client, "n", pane([*tab_b, new_row("戊", "戊答")])).status_code == 200
    response = put(client, "n", pane([new_row("己", "己答")]))
    assert response.status_code == 409
    assert "戊" in by_q(doc)


def test_a1c_two_tabs_on_an_empty_node_get_409(client, workspace):
    source = "knowledge/qa/manual_n.md"  # createDraftMergedRow 的預設路徑
    make_node(client, "n", [])
    assert merged(client, "n") == []
    assert put(client, "n", pane([new_row("第一分頁", "第一答", source)])).status_code == 200
    response = put(client, "n", pane([new_row("第二分頁", "第二答", source)]))
    assert response.status_code == 409
    assert "第一答" in (workspace / source).read_text(encoding="utf-8")


def test_a1_control_stale_editor_keeping_an_old_row_gets_409(client, workspace):
    write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n", [entry("甲"), entry("乙")])
    tab_a = merged(client, "n")
    tab_b = merged(client, "n")
    assert put(client, "n", pane([*tab_b, new_row("戊", "戊答")])).status_code == 200
    assert put(client, "n", pane(tab_a[:1])).status_code == 409


def test_a2_new_row_with_same_text_and_answer_keeps_the_file_row(client, workspace):
    """qa_merged.py:240 的註解：答案相同只是多掛一處。"""
    doc = write_doc(
        workspace, SHARED,
        "index,q,a,img,url,display\n1,甲,甲答,,,true\n2,乙,乙答,b.png,https://example.invalid/b,false\n",
    )
    make_node(client, "n1", [entry("甲")])
    make_node(client, "n2", [entry("乙", hidden=True, image_id="b.png")])
    response = put(client, "n1", pane([*merged(client, "n1"), new_row("乙", "乙答")]))
    saved = by_q(doc)["乙"]
    from knowledge import qa_nodes

    n2 = qa_nodes.get_node("n2")["qa_entries"][0]
    assert (saved["img"], saved["url"], saved["display"]) == ("b.png", "https://example.invalid/b", "false")
    assert n2["hidden"] is True and n2["image_id"] == "b.png"


def test_a3a_ingest_same_question_keeps_the_image_and_link(client, workspace):
    target = write_doc(workspace, "knowledge/qa/target.csv", "index,q,a,img,url\n1,舊題,舊答,,\n")
    dragged = write_doc(workspace, "knowledge/qa/d.csv", "q,a,img,url\n舊題,舊答,pic.png,https://example.invalid/x\n")
    make_node(client, "n", [entry("舊題", "knowledge/qa/target.csv")])
    response = client.post(f"{BASE}/nodes/n/ingest-source", json={"path": "knowledge/qa/d.csv"})
    saved = by_q(target)["舊題"]
    assert response.status_code == 400 or (saved["img"], saved["url"]) == ("pic.png", "https://example.invalid/x")



def test_a3c_ingest_keeps_markdown_preamble(client, workspace):
    write_doc(workspace, "knowledge/qa/target.md", "## 舊題\n\n舊答\n")
    dragged = write_doc(workspace, "knowledge/qa/d.md", "# 說明\n\n重要前言。\n\n## 新題\n\n新答\n")
    make_node(client, "n", [entry("舊題", "knowledge/qa/target.md")])
    response = client.post(f"{BASE}/nodes/n/ingest-source", json={"path": "knowledge/qa/d.md"})
    found = [p.name for p in (workspace / "knowledge").rglob("*.md") if "重要前言" in p.read_text(encoding="utf-8")]
    assert response.status_code == 400 or found


def test_a3d_ingest_refuses_a_regular_document(client, workspace):
    """前端拖到有題目的節點不看文件類型（useKnowledgeTreeDragDrop attachSourceToNode）。"""
    write_doc(workspace, "knowledge/qa/target.md", "## 舊題\n\n舊答\n")
    guide = write_doc(workspace, "knowledge/guide.md", "# 手冊\n\n前言段落。\n\n## 安裝\n\n步驟一。\n", source_type="upload")
    make_node(client, "n", [entry("舊題", "knowledge/qa/target.md")])
    response = client.post(f"{BASE}/nodes/n/ingest-source", json={"path": "knowledge/guide.md"})
    found = any("前言段落" in p.read_text(encoding="utf-8") for p in (workspace / "knowledge").rglob("*.md"))
    assert response.status_code == 400 and guide.exists()


def test_a3e_ingest_of_a_shared_document_keeps_other_nodes(client, workspace):
    write_doc(workspace, SHARED, "index,q,a\n1,甲,甲答\n2,乙,乙答\n")
    write_doc(workspace, "knowledge/qa/target.csv", "index,q,a\n1,舊題,舊答\n")
    make_node(client, "n1", [entry("舊題", "knowledge/qa/target.csv")])
    make_node(client, "n2", [entry("甲"), entry("乙")])
    make_node(client, "n3", [entry("甲")])
    assert client.post(f"{BASE}/nodes", json={"node_id": "kid", "label": "kid", "parent_ids": ["n3"]}).status_code == 200
    response = client.post(f"{BASE}/nodes/n1/ingest-source", json={"path": SHARED})
    from knowledge import qa_nodes

    nodes = {key: [e["question"] for e in value["qa_entries"]] for key, value in qa_nodes.list_nodes().items()}
    assert "n2" in nodes and nodes.get("n3") == ["甲"]


def test_a4a_answer_typed_on_a_menu_only_row_is_not_silently_dropped(client, workspace):
    """CorrectQaModal.applyCorrection 同題就地改答案；舊 MergedCsvPane 也強制填答案。"""
    make_node(client, "n", [])
    assert client.post(f"{BASE}/nodes/n/entries", json={"question": "選單題"}).status_code == 200
    rows = [{k: v for k, v in row.items() if k != "index"} for row in merged(client, "n")]
    rows[0]["a"] = "修正的答案"
    response = put(client, "n", rows)
    after = merged(client, "n")[0]["a"]
    in_files = any("修正的答案" in p.read_text(encoding="utf-8") for p in (workspace / "knowledge").rglob("*.*") if p.suffix in {".md", ".csv"})
    assert response.status_code != 200 or after == "修正的答案"


def test_a4b_blanking_source_file_does_not_delete_the_answer(client, workspace):
    doc = write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n", [entry("甲"), entry("乙")])
    rows = merged(client, "n")
    rows[0]["source_file"] = ""
    response = put(client, "n", rows)
    assert response.status_code != 200 or "甲" in by_q(doc)


def _edit_first_answer(client):
    loaded = merged(client, "n1")
    loaded[0]["a"] = "merged 改的"
    return loaded


def _shared_two_nodes(client, workspace):
    doc = write_doc(workspace, SHARED, "index,q,a\n1,甲,甲答\n2,乙,乙答\n3,丙,丙答\n")
    make_node(client, "n1", [entry("甲"), entry("乙")])
    make_node(client, "n2", [entry("丙")])
    return doc


    doc = write_doc(workspace, SHARED, TWO_ROWS)
    response = client.post(f"{BASE}/nodes/adopt-source", json={"path": alias})
    assert response.status_code == 200, response.text
    node_id = response.json()["node_id"]
    save = put(client, node_id, merged(client, node_id))
    assert sorted(by_q(doc)) == ["乙", "甲"]


def test_b1b_alias_mount_counts_as_mounted_elsewhere(client, workspace):
    doc = write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n1", [entry("甲"), entry("乙")])
    make_node(client, "alias", [entry("甲", f"./{SHARED}")])
    response = put(client, "n1", [row for row in merged(client, "n1") if row["q"] != "甲"])
    assert "甲" in by_q(doc)


def test_b1c_adopt_of_an_alias_is_refused_when_already_mounted(client, workspace):
    write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n1", [entry("甲"), entry("乙")])
    response = client.post(f"{BASE}/nodes/adopt-source", json={"path": f"./{SHARED}"})
    assert response.status_code == 400



def test_b1e_move_with_an_alias_does_not_lock_the_node(client, workspace):
    doc = write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n", [entry("甲"), entry("乙")])
    moved = client.post("/brain/knowledge/move", json={"source_path": SHARED, "target_path": "knowledge/qa2//a.csv", "project_id": "default"})
    assert moved.status_code == 200, moved.text
    view = merged(client, "n")
    response = put(client, "n", view)
    assert response.status_code == 200


def test_b2a_adopting_a_core_document_is_refused(client, workspace):
    """規格 4.4：source_file 與 source_path 只接受 knowledge/ 底下的 QA 文件。"""
    soul = workspace / "SOUL.md"
    original = "# 客製人設\n\n## 角色\n\n這段不在範本裡。\n"
    soul.write_text(original, encoding="utf-8")
    adopt = client.post(f"{BASE}/nodes/adopt-source", json={"path": "SOUL.md"})
    node_id = adopt.json().get("node_id") if adopt.status_code == 200 else None
    save = put(client, node_id, []) if node_id else None
    assert soul.read_text(encoding="utf-8") == original


def test_b2b_ingesting_a_core_document_is_refused(client, workspace):
    write_doc(workspace, "knowledge/qa/target.md", "## 舊題\n\n舊答\n")
    make_node(client, "n", [entry("舊題", "knowledge/qa/target.md")])
    result = {}
    for path, content in {
        "SOUL.md": "# 客製\n\n## 角色\n\n客製內容。\n",
        "personas/p1/SOUL.md": "# 人設\n\n## 分身\n\n人設內容。\n",
        "memory/2026-11-05.md": "## 今日\n\n內容\n",
    }.items():
        target = workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        response = client.post(f"{BASE}/nodes/n/ingest-source", json={"path": path})
        result[path] = [response.status_code, target.exists(), target.exists() and target.read_text(encoding="utf-8") == content]
    assert all(status == 400 and same for status, _, same in result.values())


def test_b2c_document_moved_out_of_knowledge_is_not_rewritten_by_empty_put(client, workspace):
    write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n", [entry("甲"), entry("乙")])
    assert client.post("/brain/knowledge/move", json={"source_path": SHARED, "target_path": "other/shared.csv", "project_id": "default"}).status_code == 200
    moved = workspace / "other/shared.csv"
    before = moved.read_text(encoding="utf-8")
    with_rows = put(client, "n", merged(client, "n"))
    empty = put(client, "n", [])
    assert moved.read_text(encoding="utf-8") == before


# ---------- 相對 base 的退步 ----------


def _tree_drag_last_to_first(rows):
    """useKnowledgeTreeDragDrop（a285cfe5 的前端）：只換陣列順序，index 原樣送回。"""
    return [rows[-1], *rows[:-1]]


def test_c1a_tree_drag_with_stale_index_keeps_the_order_csv(client, workspace):
    doc = write_doc(workspace, SHARED, "index,q,a\n1,甲,甲答\n2,乙,乙答\n3,丙,丙答\n")
    make_node(client, "n", [entry("甲"), entry("乙"), entry("丙")])
    response = put(client, "n", _tree_drag_last_to_first(merged(client, "n")))
    assert questions("n") == ["丙", "甲", "乙"]


def test_c1b_tree_drag_within_one_csv_of_a_two_file_node(client, workspace):
    a, b = "knowledge/qa/a.csv", "knowledge/qa/b.csv"
    write_doc(workspace, a, "index,q,a\n1,甲,甲答\n2,乙,乙答\n")
    write_doc(workspace, b, "index,q,a\n3,丙,丙答\n")
    make_node(client, "n", [entry("甲", a), entry("乙", a), entry("丙", b)])
    rows = merged(client, "n")
    response = put(client, "n", [rows[1], rows[0], rows[2]])
    assert questions("n") == ["乙", "甲", "丙"]


def test_c1_control_renumbered_index_keeps_the_order(client, workspace):
    """kb-usability 的前端已經重編 index；對照組。"""
    write_doc(workspace, SHARED, "index,q,a\n1,甲,甲答\n2,乙,乙答\n3,丙,丙答\n")
    make_node(client, "n", [entry("甲"), entry("乙"), entry("丙")])
    assert put(client, "n", pane(_tree_drag_last_to_first(merged(client, "n")))).status_code == 200
    assert questions("n") == ["丙", "甲", "乙"]


def _old_image(workspace, name):
    images = workspace / "knowledge/.qa_images"
    images.mkdir(parents=True, exist_ok=True)
    image = images / name
    image.write_bytes(b"x")
    old = time.time() - 3600
    os.utime(image, (old, old))
    return image


def test_c2a_cleanup_keeps_the_image_of_a_row_without_a_question(client, workspace):
    write_doc(workspace, SHARED, "index,q,a,img\n1,甲,甲答,\n2,,只有答案,keep.png\n")
    image = _old_image(workspace, "keep.png")
    assert client.post(f"{BASE}/nodes/adopt-source", json={"path": SHARED}).status_code == 200
    deleted = client.post(f"{BASE}/images/cleanup-unused").json()["deleted_files"]
    assert image.exists()


def test_c2b_cleanup_keeps_both_images_of_a_repeated_question(client, workspace):
    write_doc(workspace, SHARED, "index,q,a,img\n1,甲,舊答,first.png\n2,甲,新答,second.png\n")
    first, second = _old_image(workspace, "first.png"), _old_image(workspace, "second.png")
    assert client.post(f"{BASE}/nodes/adopt-source", json={"path": SHARED}).status_code == 200
    deleted = client.post(f"{BASE}/images/cleanup-unused").json()["deleted_files"]
    assert first.exists() and second.exists()


def test_c3a_get_merged_survives_a_cr_only_csv(loose, workspace):
    write_doc(workspace, SHARED, "index,q,a\r1,甲,甲答\r".encode("utf-8"))
    make_node(loose, "n", [entry("甲")])
    response = loose.get(f"{BASE}/nodes/n/merged")
    assert response.status_code == 200


def test_c3b_put_with_a_lone_cr_in_another_row_is_refused_not_500(loose, workspace):
    doc = write_doc(workspace, SHARED, 'index,q,a\n1,甲,甲答\n2,乙,"第一行\r第二行"\n'.encode("utf-8"))
    make_node(loose, "n", [entry("甲")])
    view = merged(loose, "n")
    view[0]["a"] = "甲改"
    before = doc.read_bytes()
    response = put(loose, "n", view)
    assert response.status_code in (200, 400)


def test_c4a_legacy_unnamed_entry_does_not_lock_the_node(client, workspace):
    write_doc(workspace, SHARED, "index,q,a\n1,甲,甲答\n2,,沒題目的答案\n")
    make_node(client, "n", [entry("甲"), entry("未命名問題")])
    unchanged = put(client, "n", merged(client, "n"))
    removed = put(client, "n", [row for row in merged(client, "n") if row["q"] != "未命名問題"])
    assert unchanged.status_code == 200 and removed.status_code == 200


def test_c4_control_a_document_save_unlocks_the_node(client, workspace):
    """回報 1：卡住的節點到文件頁存一次才解。這條是對照，現在就會過。"""
    content = "index,q,a\n1,甲,甲答\n2,,沒題目的答案\n"
    write_doc(workspace, SHARED, content)
    make_node(client, "n", [entry("甲"), entry("未命名問題")])
    assert client.put("/brain/knowledge/document", json={"path": SHARED, "content": content, "project_id": "default"}).status_code == 200
    assert put(client, "n", merged(client, "n")).status_code == 200


def test_c4b_mounting_the_unnamed_row_is_refused_or_saves(client, workspace):
    write_doc(workspace, SHARED, "index,q,a\n1,甲,甲答\n2,,沒題目的答案\n")
    make_node(client, "n", [entry("甲")])
    mount = client.post(f"{BASE}/nodes/n/entries", json={"question": "未命名問題", "source_path": SHARED})
    save = put(client, "n", merged(client, "n"))
    assert mount.status_code == 400 or save.status_code == 200


def test_c5_saving_one_node_does_not_delete_another_when_the_file_is_gone(client, workspace):
    from knowledge import qa_nodes

    doc = write_doc(workspace, SHARED, "index,q,a\n1,甲,甲答\n2,乙,乙答\n")
    make_node(client, "n1", [entry("甲")])
    make_node(client, "n2", [entry("乙")])
    doc.unlink()
    response = put(client, "n1", pane(merged(client, "n1")))
    assert qa_nodes.get_node("n2") is not None


# ---------- 違反規格 ----------


def test_d1a_put_refuses_same_text_from_two_files(client, workspace):
    a, b = "knowledge/qa/a.csv", "knowledge/qa/b.csv"
    write_doc(workspace, a, "index,q,a\n1,甲,甲答\n")
    write_doc(workspace, b, "index,q,a\n1,乙,乙答\n")
    make_node(client, "n", [entry("甲", a), entry("乙", b)])
    rows = merged(client, "n")
    rows[1]["q"] = "甲"
    response = put(client, "n", rows)
    assert response.status_code == 400


def test_d1b_put_refuses_a_menu_row_with_the_same_text(client, workspace):
    write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n", [entry("甲"), entry("乙")])
    response = put(client, "n", [*merged(client, "n"), {"q": "甲", "a": "", "source_file": ""}])
    assert response.status_code == 400


def test_d1c_rename_does_not_duplicate_text_on_another_node(client, workspace):
    write_doc(workspace, SHARED, "index,q,a\n1,甲,甲答\n")
    make_node(client, "n1", [entry("甲")])
    make_node(client, "n2", [entry("甲"), entry("新名字", "")])
    rows = merged(client, "n1")
    rows[0]["q"] = "新名字"
    response = put(client, "n1", rows)
    assert response.status_code == 400 or questions("n2").count("新名字") == 1


def test_d1d_document_save_does_not_duplicate_a_menu_question(client, workspace):
    doc = write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n", [entry("甲"), entry("乙")])
    assert client.post(f"{BASE}/nodes/n/entries", json={"question": "戊"}).status_code == 200
    content = doc.read_text(encoding="utf-8") + "3,戊,戊答\n"
    assert client.put("/brain/knowledge/document", json={"path": SHARED, "content": content, "project_id": "default"}).status_code == 200
    assert questions("n").count("戊") == 1


def test_d1e_ingest_checks_every_source_of_the_node(client, workspace):
    a, b, d = "knowledge/qa/a.csv", "knowledge/qa/b.csv", "knowledge/qa/d.csv"
    write_doc(workspace, a, "index,q,a\n1,甲,甲答\n")
    write_doc(workspace, b, "index,q,a\n1,乙,乙答\n")
    write_doc(workspace, d, "index,q,a\n1,乙,不同的答案\n")
    make_node(client, "n", [entry("甲", a), entry("乙", b)])
    response = client.post(f"{BASE}/nodes/n/ingest-source", json={"path": d})
    assert response.status_code == 400 or questions("n").count("乙") == 1


def test_d2_unchanged_save_follows_the_document_not_the_entry(client, workspace):
    """規格 4.4：答案、圖片、網址與隱藏都以文件為準。"""
    doc = write_doc(workspace, SHARED, "index,q,a,img,url,display\n1,甲,甲答,file.png,,true\n")
    make_node(client, "n", [entry("甲", hidden=True, image_id="stale.png")])
    rows = merged(client, "n")
    response = put(client, "n", rows)
    saved = table(doc)[0]
    assert (saved["img"], saved["display"]) == ("file.png", "true")


def test_d3_delete_entry_without_source_path_tells_the_caller(client, workspace):
    write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n", [entry("甲"), entry("乙")])
    response = client.delete(f"{BASE}/nodes/n/entries", params={"question": "甲"})
    unknown = client.delete(f"{BASE}/nodes/n/entries", params={"question": "沒有這題", "source_path": SHARED})
    assert response.status_code >= 400 or "甲" not in questions("n")



def test_d4b_serialize_keeps_language_as_the_sop_uses_it():
    """PDF_CATALOG_TO_QA_SOP：欄位列了 language，下一步用 serialize_qa_csv 產檔。"""
    from knowledge.qa_csv import serialize_qa_csv

    content = serialize_qa_csv([{"index": 1, "q": "甲", "a": "答", "img": "", "url": "", "hidden": False, "language": "en"}])
    assert "language" in content.splitlines()[0]


def test_d5a_labelling_keeps_a_manual_taiwanese_document_first(workspace):
    import knowledge.doc_meta
    from knowledge import chunking
    from memory import retrieval

    doc = write_doc(workspace, SHARED, "q,a\n你今仔日欲去佗位,阮欲去市場買菜\n")
    knowledge.doc_meta.upsert_document_meta(SHARED, "default", language="nan", language_source="manual")

    def rank():
        records = [{"metadata": json.dumps(dict(c.metadata), ensure_ascii=False)} for c in chunking._extract_csv_chunks(doc, workspace)]
        order = retrieval._language_rank(records, "nan", "zh", "default")
        return [order(r) for r in records]

    before = rank()
    label_qa_languages.label_project("default", write=True)
    assert rank() == before


def test_d5b_labelling_keeps_a_label_it_does_not_know(workspace):
    doc = write_doc(workspace, SHARED, "q,a,language\n你今仔日欲去佗位,阮欲去市場買菜,nan\n")
    label_qa_languages.label_project("default", write=True)
    assert table(doc)[0]["language"] == "nan"


def test_d5c_english_and_spanish_rows_with_a_chinese_name(workspace):
    doc = write_doc(workspace, SHARED, "q,a\nWhat does EVAK sell,EVAK (鶴記) sells submersible pumps for industrial use\n¿Qué vende EVAK?,EVAK (鶴記) vende bombas sumergibles para uso industrial\n")
    label_qa_languages.label_project("default", write=True)
    assert [row["language"] for row in table(doc)] == ["en", "es"]


def test_d5d_labelling_keeps_the_extra_cell_of_a_long_row(workspace):
    doc = write_doc(workspace, SHARED, "q,a\n營業時間是幾點,每天九點開門,多的欄\n")
    label_qa_languages.label_project("default", write=True)
    assert "多的欄" in doc.read_text(encoding="utf-8")


def test_d5e_labelling_preview_writes_nothing(workspace):
    import knowledge.doc_meta

    write_doc(workspace, SHARED, "q,a\n營業時間是幾點,每天九點開門\n")
    meta = knowledge.doc_meta.load_doc_meta("default")
    meta[SHARED].pop("language", None)
    meta[SHARED].pop("language_source", None)
    knowledge.doc_meta.save_doc_meta(meta, "default")
    path = knowledge.doc_meta.get_doc_meta_path("default")
    before = path.read_bytes()
    label_qa_languages.label_project("default")
    assert path.read_bytes() == before


def test_d5f_labelling_a_lone_cr_cell_leaves_a_readable_file(workspace, loose):
    doc = write_doc(workspace, SHARED, 'q,a\n甲,"第一行\r第二行"\n乙,乙答\n'.encode("utf-8"))
    make_node(loose, "n", [entry("甲"), entry("乙")])
    assert loose.get(f"{BASE}/nodes/n/merged").status_code == 200
    label_qa_languages.label_project("default", write=True)
    response = loose.get(f"{BASE}/nodes/n/merged")
    assert response.status_code == 200


def test_d6a_failed_sync_restores_the_nodes(loose, workspace, monkeypatch):
    import knowledge.qa_merged as qa_merged

    doc = write_doc(workspace, SHARED, TWO_ROWS)
    make_node(loose, "n1", [entry("甲"), entry("乙")])
    make_node(loose, "n2", [entry("甲")])
    payload = merged(loose, "n1")
    payload[0]["q"] = "甲改名"

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(qa_merged, "sync_entries_for_source", boom)
    response = put(loose, "n1", payload)
    assert response.status_code == 500
    assert questions("n1") == ["甲", "乙"] and questions("n2") == ["甲"]


def test_d6b_failed_new_file_leaves_no_meta(loose, workspace, monkeypatch):
    import knowledge.qa_merged as qa_merged
    from knowledge.doc_meta import load_doc_meta

    write_doc(workspace, SHARED, TWO_ROWS)
    make_node(loose, "n1", [entry("甲"), entry("乙")])

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(qa_merged, "update_node", boom)
    response = put(loose, "n1", [*merged(loose, "n1"), new_row("新", "新答", "knowledge/qa/new.csv")])
    meta_left = "knowledge/qa/new.csv" in load_doc_meta("default")
    assert not meta_left


# ---------- 異常資料 ----------


def test_e1a_markdown_with_bom_shows_and_keeps_the_first_answer(client, workspace):
    source = "knowledge/qa/bom.md"
    doc = write_doc(workspace, source, b"\xef\xbb\xbf## \xe7\x94\xb2\n\n\xe7\x94\xb2\xe7\xad\x94\n\n## \xe4\xb9\x99\n\n\xe4\xb9\x99\xe7\xad\x94\n")
    make_node(client, "n", [entry("甲", source), entry("乙", source)])
    rows = merged(client, "n")
    response = put(client, "n", rows)
    kept = "甲答" in doc.read_text(encoding="utf-8")
    assert rows[0]["a"] == "甲答" and kept


def test_e1b_sync_keeps_the_first_question_of_a_markdown_with_bom(client, workspace):
    from knowledge import qa_nodes

    source = "knowledge/qa/bom.md"
    write_doc(workspace, source, b"\xef\xbb\xbf## \xe7\x94\xb2\n\n\xe7\x94\xb2\xe7\xad\x94\n\n## \xe4\xb9\x99\n\n\xe4\xb9\x99\xe7\xad\x94\n")
    make_node(client, "n", [entry("甲", source), entry("乙", source)])
    qa_nodes.sync_entries_for_source(source)
    assert questions("n") == ["甲", "乙"]


DUPLICATES = "index,q,a\n1,甲,甲答\n2,乙,舊乙答\n3,乙,新乙答\n"


def test_e2a_removing_a_repeated_question_keeps_the_row_nobody_saw(client, workspace):
    doc = write_doc(workspace, SHARED, DUPLICATES)
    make_node(client, "n", [entry("甲"), entry("乙")])
    response = put(client, "n", [row for row in merged(client, "n") if row["q"] != "乙"])
    assert "舊乙答" in {row["a"] for row in table(doc)}



def test_e2c_saving_a_repeated_question_keeps_the_answer_shown(client, workspace):
    write_doc(workspace, SHARED, DUPLICATES)
    make_node(client, "n", [entry("乙"), entry("甲")])
    rows = merged(client, "n")
    assert {row["q"]: row["a"] for row in rows}["乙"] == "新乙答"
    response = put(client, "n", rows)
    after = {row["q"]: row["a"] for row in merged(client, "n")}["乙"]
    assert after == "新乙答"



def test_e4a_unknown_original_q_with_an_existing_q_keeps_custom_columns(client, workspace):
    doc = write_doc(workspace, SHARED, "index,q,a,備註\n1,甲,甲答,甲註\n2,乙,乙答,乙註\n")
    make_node(client, "n", [entry("甲"), entry("乙")])
    rows = merged(client, "n")
    rows[0]["original_q"] = "沒有這題"
    response = put(client, "n", rows)
    assert by_q(doc)["甲"]["備註"] == "甲註"


def test_e4b_hidden_null_keeps_the_current_state(client, workspace):
    doc = write_doc(workspace, SHARED, "index,q,a,display\n1,甲,甲答,false\n")
    make_node(client, "n", [entry("甲", hidden=True)])
    rows = merged(client, "n")
    rows[0]["hidden"] = None
    response = put(client, "n", rows)
    assert by_q(doc)["甲"]["display"] == "false"


def test_e4c_system_folder_is_not_accepted_as_a_document(client, workspace):
    from knowledge import qa_nodes

    write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n", [entry("甲"), entry("乙")])
    response = put(client, "n", [*merged(client, "n"), new_row("x", "重要答案", "knowledge/.qa_images/x.md")])
    doc = workspace / "knowledge/.qa_images/x.md"
    if response.status_code != 200:
        return
    old = time.time() - 3600
    os.utime(doc, (old, old))
    qa_nodes.cleanup_unused_images("default")
    assert doc.exists()


def test_e4d_node_deleted_during_put_is_reported(client, workspace, monkeypatch):
    doc = _shared_two_nodes(client, workspace)
    loaded = _edit_first_answer(client)
    state = during_write(monkeypatch, lambda: client.delete(f"{BASE}/nodes/n1").status_code)
    response = put(client, "n1", loaded)
    state["thread"].join(10)
    assert response.status_code != 200




def test_e5c_migrate_script_keeps_unattached_qa_documents(client, workspace):
    import knowledge.doc_meta
    from scripts import migrate_qa_paths

    source = "knowledge/qa/own.md"
    write_doc(workspace, source, "## 甲\n\n甲答\n")
    make_node(client, "n", [entry("甲", source)])
    assert client.delete(f"{BASE}/nodes/n").status_code == 200
    if not (workspace / source).exists():
        pytest.skip("base 刪節點連文件一起刪")
    migrate_qa_paths.get_workspace_root = lambda project_id="default": workspace
    migrate_qa_paths.migrate_project_qa_paths("default")
    source_type = knowledge.doc_meta.get_document_meta(source, "default")["source_type"]
    assert source_type == "qa"


def test_a3b_ingest_refuses_columns_the_target_cannot_hold(client, workspace):
    target = write_doc(workspace, "knowledge/qa/target.csv", "index,q,a,language\n1,舊題,舊答,zh\n")
    dragged = write_doc(workspace, "knowledge/qa/d.csv", "q,a,language,備註\nHello,World,en,保留\n")
    make_node(client, "n", [entry("舊題", "knowledge/qa/target.csv")])
    before = target.read_bytes()

    response = client.post(f"{BASE}/nodes/n/ingest-source", json={"path": "knowledge/qa/d.csv"})

    assert response.status_code == 400
    assert dragged.exists()
    assert target.read_bytes() == before


def test_e2b_renaming_a_repeated_question_is_refused(client, workspace):
    doc = write_doc(workspace, SHARED, DUPLICATES)
    make_node(client, "n", [entry("甲"), entry("乙")])
    before = doc.read_bytes()
    rows = merged(client, "n")
    next(row for row in rows if row["q"] == "乙")["q"] = "乙改"

    assert put(client, "n", rows).status_code == 400

    assert doc.read_bytes() == before
    assert questions("n") == ["甲", "乙"]


def test_deleting_every_row_needs_the_loaded_version(client, workspace):
    doc = write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n", [entry("甲"), entry("乙")])
    version = merged(client, "n")[0]["base_version"]

    assert client.put(f"{BASE}/nodes/n/merged?base_version=stale", json=[]).status_code == 409
    assert client.put(f"{BASE}/nodes/n/merged?base_version={version}", json=[]).status_code == 200

    assert table(doc) == []


def test_a5b_document_delete_during_put_stays_deleted(client, workspace, monkeypatch):
    doc = _shared_two_nodes(client, workspace)
    loaded = _edit_first_answer(client)
    state = during_write(monkeypatch, lambda: client.delete(
        "/brain/knowledge/document", params={"path": SHARED},
    ).status_code)
    merged_status = put(client, "n1", loaded).status_code
    state["thread"].join(10)
    assert not doc.exists()


def test_a5c_move_during_put_leaves_one_file_with_the_edit(client, workspace, monkeypatch):
    doc = _shared_two_nodes(client, workspace)
    target = workspace / "knowledge/moved/s.csv"
    loaded = _edit_first_answer(client)
    state = during_write(monkeypatch, lambda: client.post(
        "/brain/knowledge/move",
        json={"source_path": SHARED, "target_path": "knowledge/moved/s.csv", "project_id": "default"},
    ).status_code)
    merged_status = put(client, "n1", loaded).status_code
    state["thread"].join(10)
    from knowledge import qa_nodes

    assert not doc.exists() and "merged 改的" in target.read_text(encoding="utf-8")


def test_a6_reuploading_a_mounted_document_keeps_it_a_qa_document(client, workspace):
    doc = _shared_two_nodes(client, workspace)
    response = client.post(
        "/brain/knowledge/upload",
        data={"target_dir": "knowledge/qa", "project_id": "default"},
        files=[("files", ("shared.csv", doc.read_bytes(), "text/csv"))],
    )
    assert response.status_code == 200, response.text
    from knowledge.doc_meta import get_document_meta

    tag = get_document_meta(SHARED, "default")["source_type"]
    moved = client.post("/brain/knowledge/move", json={"source_path": SHARED, "target_path": "knowledge/qa/moved.csv", "project_id": "default"})
    view = merged(client, "n1")
    resave = put(client, "n1", pane(view))
    assert [row["a"] for row in view] == ["甲答", "乙答"] and questions("n1") == ["甲", "乙"]


def test_b1d_delete_with_an_alias_clears_mounts_and_meta(client, workspace):
    from knowledge import qa_nodes
    from knowledge.doc_meta import load_doc_meta

    write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n", [entry("甲"), entry("乙")])
    response = client.delete("/brain/knowledge/document", params={"path": f"./{SHARED}"})
    node = qa_nodes.get_node("n")
    assert node is None and SHARED not in load_doc_meta("default")


def test_a5a_document_page_with_a_stale_copy_is_refused(client, workspace, monkeypatch):
    doc = _shared_two_nodes(client, workspace)
    loaded = _edit_first_answer(client)
    opened = client.get("/brain/knowledge/document", params={"path": SHARED}).json()
    content = opened["content"] + "4,文件頁新題,文件頁答\n"
    state = during_write(monkeypatch, lambda: client.put(
        "/brain/knowledge/document",
        json={"path": SHARED, "content": content, "project_id": "default", "base_hash": opened["content_hash"]},
    ).status_code)

    assert put(client, "n1", loaded).status_code == 200
    state["thread"].join(10)

    # 鎖讓文件頁等問答存完；它拿的是舊全文，所以被拒絕，問答剛存的內容留著。
    assert state["status"] == 409
    assert "merged 改的" in doc.read_text(encoding="utf-8")


def test_refilling_an_emptied_category_forgets_what_was_taken_off_the_menu(client, workspace):
    from knowledge import qa_nodes

    write_doc(workspace, SHARED, TWO_ROWS)
    make_node(client, "n", [entry("甲"), entry("乙")])
    assert client.delete(f"{BASE}/nodes/n/entries", params={"question": "甲", "source_path": SHARED}).status_code == 200
    assert "甲" in qa_nodes._load_nodes_data()["detached"][SHARED]

    data = qa_nodes._load_nodes_data()
    data["detached"][SHARED] = ["甲"]
    qa_nodes._save_nodes_data(data)
    qa_nodes.update_node("n", {"qa_entries": []})
    monkey_label = qa_nodes._source_node_id
    try:
        qa_nodes._source_node_id = lambda label: "n"
        assert qa_nodes.refill_emptied_node(SHARED, "shared") is not None
    finally:
        qa_nodes._source_node_id = monkey_label

    assert SHARED not in qa_nodes._load_nodes_data().get("detached", {})



def test_reordering_a_file_with_a_question_taken_off_the_menu(client, workspace):
    """審查重現：拿下選單的列讓檔案看起來像共用，存檔不重排，同步又照檔案排回去。"""
    for source, content in (
        ("knowledge/qa/own.csv", "index,q,a\n1,甲,甲答\n2,乙,乙答\n3,丙,丙答\n"),
        ("knowledge/qa/own.md", "## 甲\n\n甲答\n\n## 乙\n\n乙答\n\n## 丙\n\n丙答\n"),
    ):
        write_doc(workspace, source, content)
        node_id = source.rsplit(".", 1)[1]
        make_node(client, node_id, [entry("甲", source), entry("乙", source), entry("丙", source)])
        assert client.delete(f"{BASE}/nodes/{node_id}/entries", params={"question": "丙", "source_path": source}).status_code == 200

        assert put(client, node_id, list(reversed(merged(client, node_id)))).status_code == 200

        assert questions(node_id) == ["乙", "甲"]


def test_renormalizing_through_a_path_alias_is_refused(client, workspace):
    doc = write_doc(workspace, "knowledge/qa/q.md", "## 甲\n\n甲答\n")
    make_node(client, "n", [entry("甲", "knowledge/qa/q.md")])

    response = client.post(
        "/brain/knowledge/renormalize/apply",
        json={"path": "./knowledge/qa/q.md", "content": "garbage", "project_id": "default"},
    )

    assert response.status_code == 400
    assert doc.read_text(encoding="utf-8") == "## 甲\n\n甲答\n"

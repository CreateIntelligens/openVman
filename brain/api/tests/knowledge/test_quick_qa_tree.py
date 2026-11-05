"""快速問答樹與文件脫鉤後的行為：一份文件可分給多個節點，題目也可以不來自文件。"""

from __future__ import annotations

import csv
import io
import os
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from main import app  # noqa: E402

SHARED_CSV = "knowledge/qa/shared.csv"
_SHARED_CONTENT = (
    "index,q,a,img,url,display,備註\n"
    "10,甲題,甲答,,,true,甲的備註\n"
    "20,乙題,乙答,,,true,乙的備註\n"
    "30,丙題,丙答,,,false,丙的備註\n"
    "40,丁題,丁答,,,true,\n"
)


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

    class FakeEmbedder:
        def encode(self, texts, **kwargs):
            return [[0.1] * 768 for _ in texts]

    monkeypatch.setattr(memory.embedder, "get_embedder", lambda *a, **k: FakeEmbedder())
    return root


@pytest.fixture
def client(workspace) -> TestClient:
    from config import get_settings

    return TestClient(app, headers={"X-Internal-Token": get_settings().gateway_internal_token})


def _entry(question: str, source: str = SHARED_CSV, hidden: bool = False) -> dict:
    return {"question": question, "source_path": source, "hidden": hidden, "image_id": None}


def _write_doc(root: Path, relative: str, content: str) -> Path:
    import knowledge.doc_meta

    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta(relative, "default", source_type="qa")
    return path


@pytest.fixture
def shared(workspace, client) -> Path:
    """n1 掛甲乙，n2 掛丙丁，同一份 CSV。"""
    from knowledge import qa_nodes

    doc = _write_doc(workspace, SHARED_CSV, _SHARED_CONTENT)
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n1", "label": "一"})
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n2", "label": "二"})
    qa_nodes.update_node("n1", {"qa_entries": [_entry("甲題"), _entry("乙題")]})
    qa_nodes.update_node("n2", {"qa_entries": [_entry("丙題", hidden=True), _entry("丁題")]})
    return doc


def _rows(doc: Path) -> dict[str, dict[str, str]]:
    return {row["q"]: row for row in csv.DictReader(io.StringIO(doc.read_text(encoding="utf-8")))}


def _questions(node_id: str) -> list[str]:
    from knowledge import qa_nodes

    return [entry["question"] for entry in qa_nodes.get_node(node_id)["qa_entries"]]


def _merged(client: TestClient, node_id: str) -> list[dict]:
    response = client.get(f"/brain/knowledge/qa/nodes/{node_id}/merged")
    assert response.status_code == 200
    return response.json()


def _put_merged(client: TestClient, node_id: str, rows: list[dict]):
    return client.put(f"/brain/knowledge/qa/nodes/{node_id}/merged", json=rows)


# --- PUT /merged 只動這個節點的題目 ---


def test_editing_one_node_keeps_the_rows_of_another_node(client, shared):
    rows = _merged(client, "n1")
    rows[0]["a"] = "甲的新答案"

    assert _put_merged(client, "n1", rows).status_code == 200

    saved = _rows(shared)
    assert saved["甲題"]["a"] == "甲的新答案"
    assert saved["丙題"]["a"] == "丙答"
    assert saved["丁題"]["a"] == "丁答"
    assert saved["丙題"]["display"] == "false"
    assert saved["丙題"]["index"] == "30"
    assert saved["丁題"]["index"] == "40"
    assert _questions("n2") == ["丙題", "丁題"]


def test_editing_keeps_custom_columns_on_every_row(client, shared):
    rows = _merged(client, "n1")
    rows[0]["a"] = "甲的新答案"

    _put_merged(client, "n1", rows)

    saved = _rows(shared)
    assert saved["甲題"]["備註"] == "甲的備註"
    assert saved["丙題"]["備註"] == "丙的備註"


def test_reordering_a_shared_file_only_changes_this_node(client, shared):
    rows = list(reversed(_merged(client, "n1")))

    assert _put_merged(client, "n1", rows).status_code == 200

    assert _questions("n1") == ["乙題", "甲題"]
    assert _questions("n2") == ["丙題", "丁題"]
    # 檔案分給多個節點時，順序記在節點上，檔案的列與 index 都不動。
    assert shared.read_text(encoding="utf-8") == _SHARED_CONTENT


def test_editing_a_question_on_two_nodes_does_not_reorder_the_other_node(client, shared):
    """dev 實測：從第二個分類改答案，第一個分類的選單順序被檔案順序打亂。"""
    from knowledge import qa_nodes

    qa_nodes.add_qa_entry_to_node("n2", _entry("甲題"))
    rows = _merged(client, "n2")
    assert [row["q"] for row in rows] == ["丙題", "丁題", "甲題"]
    rows[2]["a"] = "從 n2 改的答案"

    assert _put_merged(client, "n2", rows).status_code == 200

    assert _questions("n1") == ["甲題", "乙題"]
    assert _questions("n2") == ["丙題", "丁題", "甲題"]
    saved = shared.read_text(encoding="utf-8")
    assert saved == _SHARED_CONTENT.replace("10,甲題,甲答,", "10,甲題,從 n2 改的答案,")


def test_a_file_owned_by_one_node_still_takes_the_screen_order(client, workspace):
    from knowledge import qa_nodes

    doc = _write_doc(workspace, "knowledge/qa/own.csv", "index,q,a\n1,甲,甲答\n2,乙,乙答\n")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n", "label": "N"})
    qa_nodes.update_node("n", {"qa_entries": [_entry("甲", "knowledge/qa/own.csv"), _entry("乙", "knowledge/qa/own.csv")]})
    rows = list(reversed(_merged(client, "n")))
    rows[0]["index"], rows[1]["index"] = "1", "2"

    assert _put_merged(client, "n", rows).status_code == 200

    assert _questions("n") == ["乙", "甲"]
    assert _rows(doc)["乙"]["index"] == "1"
    assert _rows(doc)["甲"]["index"] == "2"


def test_a_question_on_two_nodes_changes_everywhere(client, shared):
    from knowledge import qa_nodes

    qa_nodes.add_qa_entry_to_node("n2", _entry("甲題"))
    rows = _merged(client, "n1")
    rows[0]["q"] = "甲題改名"
    rows[0]["a"] = "新答案"
    rows[0]["hidden"] = True

    assert _put_merged(client, "n1", rows).status_code == 200

    saved = _rows(shared)
    assert "甲題" not in saved
    assert saved["甲題改名"]["a"] == "新答案"
    assert saved["甲題改名"]["備註"] == "甲的備註"
    mounted = {e["question"]: e for e in qa_nodes.get_node("n2")["qa_entries"]}
    assert "甲題" not in mounted
    assert mounted["甲題改名"]["hidden"] is True


def test_removing_a_question_on_another_node_only_unmounts_it(client, shared):
    from knowledge import qa_nodes

    qa_nodes.add_qa_entry_to_node("n2", _entry("甲題"))
    rows = [row for row in _merged(client, "n1") if row["q"] != "甲題"]

    assert _put_merged(client, "n1", rows).status_code == 200

    assert "甲題" in _rows(shared)
    assert _questions("n1") == ["乙題"]
    assert "甲題" in _questions("n2")


def test_removing_a_question_no_other_node_has_deletes_the_row(client, shared):
    rows = [row for row in _merged(client, "n1") if row["q"] != "甲題"]

    assert _put_merged(client, "n1", rows).status_code == 200

    assert set(_rows(shared)) == {"乙題", "丙題", "丁題"}


def test_a_new_row_cannot_overwrite_another_node_answer(client, shared):
    before = shared.read_bytes()
    rows = _merged(client, "n1")
    rows.append({"q": "丁題", "a": "別的答案", "source_file": SHARED_CSV})

    response = _put_merged(client, "n1", rows)

    assert response.status_code == 400
    assert "丁題" in response.json()["detail"]
    assert shared.read_bytes() == before
    assert _questions("n1") == ["甲題", "乙題"]


def test_renaming_onto_an_existing_question_is_rejected(client, shared):
    before = shared.read_bytes()
    rows = _merged(client, "n1")
    rows[0]["q"] = "乙題"

    response = _put_merged(client, "n1", rows)

    assert response.status_code == 400
    assert shared.read_bytes() == before


def test_a_row_that_would_not_read_back_is_not_written(client, workspace):
    from knowledge import qa_nodes

    source = "knowledge/qa/note.md"
    doc = _write_doc(workspace, source, "## 甲\n\n甲答\n")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n", "label": "N"})
    qa_nodes.update_node("n", {"qa_entries": [_entry("甲", source)]})
    before = doc.read_bytes()
    rows = _merged(client, "n")
    rows[0]["a"] = "前段\n## 會被當成另一題\n後段"

    response = _put_merged(client, "n", rows)

    assert response.status_code == 400
    assert doc.read_bytes() == before


def test_markdown_text_before_the_first_question_survives(client, workspace):
    from knowledge import qa_nodes

    source = "knowledge/qa/note.md"
    doc = _write_doc(workspace, source, "# 門市須知\n\n開頭說明\n\n## 甲\n\n甲答\n")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n", "label": "N"})
    qa_nodes.update_node("n", {"qa_entries": [_entry("甲", source)]})
    rows = _merged(client, "n")
    rows[0]["a"] = "新答"

    assert _put_merged(client, "n", rows).status_code == 200

    content = doc.read_text(encoding="utf-8")
    assert content.startswith("# 門市須知\n\n開頭說明")
    assert "新答" in content


def test_removing_every_row_keeps_the_file(client, workspace):
    from knowledge import qa_nodes

    source = "knowledge/qa/own.csv"
    doc = _write_doc(workspace, source, "index,q,a,備註\n1,甲,甲答,\n,,,只有備註的列\n")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n", "label": "N"})
    qa_nodes.update_node("n", {"qa_entries": [_entry("甲", source)]})

    version = _merged(client, "n")[0]["base_version"]
    assert client.put(f"/brain/knowledge/qa/nodes/n/merged?base_version={version}", json=[]).status_code == 200

    content = doc.read_text(encoding="utf-8")
    assert "甲答" not in content
    assert "只有備註的列" in content
    assert qa_nodes.get_node("n")["qa_entries"] == []


def test_merged_keeps_the_node_order_across_files(client, workspace):
    from knowledge import qa_nodes

    _write_doc(workspace, "knowledge/qa/a.md", "## A1\n\nx\n\n## A2\n\ny\n")
    _write_doc(workspace, "knowledge/qa/b.md", "## B1\n\nz\n")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n", "label": "N"})
    qa_nodes.update_node("n", {"qa_entries": [
        _entry("A1", "knowledge/qa/a.md"),
        _entry("B1", "knowledge/qa/b.md"),
        _entry("A2", "knowledge/qa/a.md"),
    ]})

    assert [row["q"] for row in _merged(client, "n")] == ["A1", "B1", "A2"]


def test_merged_says_where_else_a_question_is_mounted(client, shared):
    from knowledge import qa_nodes

    qa_nodes.add_qa_entry_to_node("n2", _entry("甲題"))

    rows = {row["q"]: row for row in _merged(client, "n1")}

    assert rows["甲題"]["also_in"] == ["二"]
    assert rows["乙題"]["also_in"] == []


# --- 同步：文件改了，樹跟著改，但不把整份文件塞進每個節點 ---


def test_syncing_a_shared_file_does_not_copy_it_into_every_node(shared):
    from knowledge import qa_nodes

    assert qa_nodes.sync_entries_for_source(SHARED_CSV) == 2

    assert _questions("n1") == ["甲題", "乙題"]
    assert _questions("n2") == ["丙題", "丁題"]


def test_a_new_question_in_a_shared_file_lands_on_one_node(shared):
    from knowledge import qa_nodes

    shared.write_text(_SHARED_CONTENT + "50,戊題,戊答,,,true,\n", encoding="utf-8")

    qa_nodes.sync_entries_for_source(SHARED_CSV)

    assert _questions("n1") == ["甲題", "乙題", "戊題"]
    assert _questions("n2") == ["丙題", "丁題"]


def test_a_question_removed_from_the_file_leaves_every_node(shared):
    from knowledge import qa_nodes

    qa_nodes.add_qa_entry_to_node("n2", _entry("甲題"))
    shared.write_text(_SHARED_CONTENT.replace("10,甲題,甲答,,,true,甲的備註\n", ""), encoding="utf-8")

    qa_nodes.sync_entries_for_source(SHARED_CSV)

    assert _questions("n1") == ["乙題"]
    assert "甲題" not in _questions("n2")


def test_hidden_follows_the_file_on_every_mount(shared):
    from knowledge import qa_nodes

    qa_nodes.add_qa_entry_to_node("n1", _entry("丙題"))

    qa_nodes.sync_entries_for_source(SHARED_CSV)

    entry = next(e for e in qa_nodes.get_node("n1")["qa_entries"] if e["question"] == "丙題")
    assert entry["hidden"] is True


def test_reimporting_a_file_keeps_the_node_label_and_parent(client, workspace):
    from knowledge import qa_nodes

    source = "knowledge/qa/faq.csv"
    doc = _write_doc(workspace, source, "index,q,a\n1,甲,甲答\n")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "root", "label": "中文"})
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n", "label": "改過的名字", "parent_ids": ["root"]})
    qa_nodes.update_node("n", {"qa_entries": [_entry("甲", source)]})
    doc.write_text("index,q,a\n1,甲,甲答新版\n2,乙,乙答\n", encoding="utf-8")

    qa_nodes.sync_entries_for_source(source)

    node = qa_nodes.get_node("n")
    assert node["label"] == "改過的名字"
    assert node["parent_ids"] == ["root"]
    assert _questions("n") == ["甲", "乙"]


def test_other_sources_keep_their_place_when_one_file_syncs(client, workspace):
    from knowledge import qa_nodes

    _write_doc(workspace, "knowledge/qa/a.md", "## A1\n\nx\n\n## A2\n\ny\n")
    _write_doc(workspace, "knowledge/qa/b.md", "## B1\n\nz\n")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n", "label": "N"})
    qa_nodes.update_node("n", {"qa_entries": [
        _entry("A1", "knowledge/qa/a.md"),
        _entry("B1", "knowledge/qa/b.md"),
        _entry("A2", "knowledge/qa/a.md"),
    ]})

    qa_nodes.sync_entries_for_source("knowledge/qa/a.md")

    assert _questions("n") == ["A1", "B1", "A2"]


def test_a_file_that_reads_as_empty_does_not_empty_the_tree(client, workspace):
    from knowledge import qa_nodes

    source = "knowledge/qa/note.md"
    doc = _write_doc(workspace, source, "## 甲\n\n甲答\n")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n", "label": "N"})
    qa_nodes.update_node("n", {"qa_entries": [_entry("甲", source)]})
    doc.write_text("改到一半，標題被拿掉了", encoding="utf-8")

    assert qa_nodes.sync_entries_for_source(source) == 0

    assert _questions("n") == ["甲"]


def test_deleting_a_document_leaves_unrelated_empty_categories(client, shared):
    from knowledge import qa_nodes

    client.post("/brain/knowledge/qa/nodes", json={"node_id": "empty", "label": "還沒放題目"})

    qa_nodes.remove_entries_for_source(SHARED_CSV)

    assert qa_nodes.get_node("empty") is not None
    assert qa_nodes.get_node("n1") is None


# --- 刪節點不刪文件 ---


def test_deleting_a_node_keeps_its_document(client, shared):
    import knowledge.doc_meta

    response = client.delete("/brain/knowledge/qa/nodes/n1")
    assert response.status_code == 200
    response = client.delete("/brain/knowledge/qa/nodes/n2")
    assert response.status_code == 200

    assert shared.exists()
    assert SHARED_CSV in knowledge.doc_meta.load_doc_meta("default")


def test_a_document_without_a_node_does_not_grow_one_back(client, shared):
    client.delete("/brain/knowledge/qa/nodes/n1")
    client.delete("/brain/knowledge/qa/nodes/n2")

    assert client.get("/brain/knowledge/qa/nodes").json() == []


def test_cleanup_keeps_images_only_a_document_refers_to(client, workspace):
    from knowledge import qa_nodes

    images = workspace / "knowledge" / ".qa_images"
    images.mkdir(parents=True, exist_ok=True)
    used = images / "used.png"
    unused = images / "unused.png"
    for image in (used, unused):
        image.write_bytes(b"x")
        old = time.time() - 3600
        os.utime(image, (old, old))
    _write_doc(workspace, "knowledge/qa/faq.csv", "index,q,a,img\n1,甲,甲答,used.png\n")

    qa_nodes.cleanup_unused_images()

    assert used.exists()
    assert not unused.exists()


# --- 選單專用題目 ---


def _add_entry(client: TestClient, node_id: str, **body):
    return client.post(f"/brain/knowledge/qa/nodes/{node_id}/entries", json=body)


def test_menu_only_question_needs_no_document(client, workspace):
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n", "label": "N"})

    response = _add_entry(client, "n", question=" 今天有什麼活動 ")

    assert response.status_code == 200
    rows = _merged(client, "n")
    assert rows[0]["q"] == "今天有什麼活動"
    assert rows[0]["source_file"] == ""
    assert rows[0]["a"] == ""
    assert client.get("/brain/knowledge/qa/nodes").json()[0]["qa_entries"][0]["question"] == "今天有什麼活動"


def test_saving_a_node_keeps_menu_only_questions_out_of_files(client, shared):
    _add_entry(client, "n1", question="今天有什麼活動")
    before = {path: path.read_bytes() for path in (shared,)}
    rows = _merged(client, "n1")
    rows[0]["a"] = "甲的新答案"
    menu_row = next(row for row in rows if row["source_file"] == "")
    menu_row["hidden"] = True

    assert _put_merged(client, "n1", rows).status_code == 200

    assert "今天有什麼活動" not in shared.read_text(encoding="utf-8")
    assert shared.read_bytes() != before[shared]
    from knowledge import qa_nodes

    entries = {e["question"]: e for e in qa_nodes.get_node("n1")["qa_entries"]}
    assert entries["今天有什麼活動"]["hidden"] is True
    assert entries["今天有什麼活動"]["source_path"] == ""
    assert list(entries) == ["甲題", "乙題", "今天有什麼活動"]


def test_syncing_a_file_leaves_menu_only_questions(client, shared):
    from knowledge import qa_nodes

    _add_entry(client, "n1", question="今天有什麼活動")

    qa_nodes.sync_entries_for_source(SHARED_CSV)

    assert "今天有什麼活動" in _questions("n1")


def test_a_node_with_only_menu_questions_ingests_into_a_new_file(client, workspace):
    source = _write_doc(workspace, "knowledge/qa/dragged.md", "## 甲\n\n甲答\n")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n", "label": "N"})
    _add_entry(client, "n", question="今天有什麼活動")

    response = client.post(
        "/brain/knowledge/qa/nodes/n/ingest-source",
        json={"path": "knowledge/qa/dragged.md"},
    )

    assert response.status_code == 200
    assert not source.exists()
    assert (workspace / "knowledge" / "qa" / "n.md").exists()
    assert _questions("n") == ["今天有什麼活動", "甲"]


# --- 同一題掛多個節點 ---


def test_mounting_a_question_on_a_second_node(client, shared):
    from knowledge import qa_nodes

    response = _add_entry(client, "n2", question="甲題", source_path=SHARED_CSV)

    assert response.status_code == 200
    assert _questions("n2") == ["丙題", "丁題", "甲題"]
    assert _questions("n1") == ["甲題", "乙題"]
    assert len(_rows(shared)) == 4
    assert qa_nodes.get_node("n2")["qa_entries"][2]["source_path"] == SHARED_CSV


def test_mounting_takes_hidden_from_the_document(client, shared):
    from knowledge import qa_nodes

    _add_entry(client, "n1", question="丙題", source_path=SHARED_CSV)

    entry = next(e for e in qa_nodes.get_node("n1")["qa_entries"] if e["question"] == "丙題")
    assert entry["hidden"] is True


@pytest.mark.parametrize("question, source_path, status", [
    ("沒有這題", SHARED_CSV, 400),
    ("甲題", "knowledge/qa/missing.csv", 404),
    ("甲題", "../outside.csv", 400),
])
def test_mounting_rejects_what_the_document_does_not_have(client, shared, question, source_path, status):
    response = _add_entry(client, "n2", question=question, source_path=source_path)

    assert response.status_code == status
    assert _questions("n2") == ["丙題", "丁題"]


def test_the_same_text_twice_on_one_node_is_rejected(client, shared):
    response = _add_entry(client, "n1", question="甲題")

    assert response.status_code == 400
    assert _questions("n1") == ["甲題", "乙題"]


def test_blank_question_is_rejected(client, shared):
    assert _add_entry(client, "n1", question="   ").status_code == 400


def test_taking_a_question_off_the_menu_keeps_it_in_the_file_and_off_the_menu(client, shared):
    from knowledge import qa_nodes

    response = client.delete(
        "/brain/knowledge/qa/nodes/n1/entries",
        params={"question": "甲題", "source_path": SHARED_CSV},
    )

    assert response.status_code == 200
    assert _questions("n1") == ["乙題"]
    assert "甲題" in _rows(shared)

    qa_nodes.sync_entries_for_source(SHARED_CSV)

    assert _questions("n1") == ["乙題"]
    assert "甲題" not in _questions("n2")

    assert _add_entry(client, "n2", question="甲題", source_path=SHARED_CSV).status_code == 200
    assert "甲題" in _questions("n2")


def test_unmounting_a_second_mount_keeps_the_row(client, shared):
    _add_entry(client, "n2", question="甲題", source_path=SHARED_CSV)

    response = client.delete(
        "/brain/knowledge/qa/nodes/n1/entries",
        params={"question": "甲題", "source_path": SHARED_CSV},
    )

    assert response.status_code == 200
    assert _questions("n1") == ["乙題"]
    assert "甲題" in _questions("n2")
    assert "甲題" in _rows(shared)


def test_removing_a_menu_only_question(client, shared):
    _add_entry(client, "n1", question="今天有什麼活動")

    response = client.delete(
        "/brain/knowledge/qa/nodes/n1/entries",
        params={"question": "今天有什麼活動"},
    )

    assert response.status_code == 200
    assert _questions("n1") == ["甲題", "乙題"]


# --- 每題語言 ---


@pytest.mark.parametrize("raw, expected", [
    ("en", "en"), ("English", "en"), ("zh-TW", "zh"), ("中文", "zh"),
    ("Español", "es"), ("", None), ("klingon", None),
])
def test_row_language_labels(raw, expected):
    from knowledge.qa_csv import normalize_row_language

    assert normalize_row_language(raw) == expected


def test_csv_chunks_carry_their_row_language(workspace):
    from knowledge.chunking import _extract_csv_chunks

    doc = _write_doc(
        workspace,
        "knowledge/qa/mixed.csv",
        "index,q,a,語言\n1,甲,甲答,中文\n2,Hours,Open daily,en\n3,沒標,答,\n4,亂標,答,klingon\n",
    )

    chunks = _extract_csv_chunks(doc, workspace)

    assert [chunk.metadata.get("language") for chunk in chunks] == ["zh", "en", None, None]


def test_row_language_wins_over_the_document_language():
    from memory.retrieval import _language_rank

    records = [
        {"metadata": '{"path": "knowledge/qa/mixed.csv", "language": "en"}'},
        {"metadata": '{"path": "knowledge/qa/mixed.csv", "language": "es"}'},
        {"metadata": '{"path": "knowledge/qa/mixed.csv"}'},
    ]
    import memory.retrieval as retrieval

    original = retrieval.resolve_document_languages
    retrieval.resolve_document_languages = lambda paths, project_id: {"knowledge/qa/mixed.csv": "zh"}
    try:
        rank = _language_rank(records, "en", "zh", "default")
    finally:
        retrieval.resolve_document_languages = original

    assert [rank(record) for record in records] == [0, 2, 1]


def test_labelling_fills_only_blank_rows():
    from knowledge.qa_csv import label_qa_csv_languages

    source = "q,a,備註,語言\n甲,甲答,留著,en\n乙,乙答,,\n丙,丙答,,klingon\n".encode("utf-8")

    content, counts = label_qa_csv_languages(source, lambda text: "zh")

    rows = list(csv.DictReader(io.StringIO(content)))
    assert [row["語言"] for row in rows] == ["en", "zh", "klingon"]
    assert rows[0]["備註"] == "留著"
    assert counts == {"en": 1, "zh": 1, "klingon": 1}


def test_labelling_script_previews_unless_told_to_write(workspace, monkeypatch):
    import scripts.label_qa_languages as script
    from scripts.label_qa_languages import label_project

    # 別的測試 reload 過 knowledge_admin，它綁的核心文件路徑還指著那個測試的暫存目錄。
    monkeypatch.setattr(
        script,
        "save_workspace_document",
        lambda path, content, project_id: (workspace / path).write_text(content, encoding="utf-8"),
    )
    doc = _write_doc(
        workspace,
        "knowledge/qa/mixed.csv",
        "q,a\n營業時間是幾點,每天早上九點開門\nWhat are your opening hours,We are open every day from nine\n",
    )
    before = doc.read_bytes()

    preview = label_project("default")

    assert preview["knowledge/qa/mixed.csv"] == {"zh": 1, "en": 1}
    assert doc.read_bytes() == before

    label_project("default", write=True)

    rows = list(csv.DictReader(io.StringIO(doc.read_text(encoding="utf-8"))))
    assert [row["language"] for row in rows] == ["zh", "en"]


def test_saving_a_node_keeps_row_languages(client, workspace):
    from knowledge import qa_nodes

    source = "knowledge/qa/mixed.csv"
    doc = _write_doc(workspace, source, "index,q,a,language\n1,甲,甲答,zh\n2,Hours,Open,en\n")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n", "label": "N"})
    qa_nodes.update_node("n", {"qa_entries": [_entry("甲", source), _entry("Hours", source)]})
    rows = _merged(client, "n")
    rows[1]["a"] = "Open daily"

    assert _put_merged(client, "n", rows).status_code == 200

    assert _rows(doc)["Hours"]["language"] == "en"
    assert _rows(doc)["Hours"]["a"] == "Open daily"


# --- 審查找到的情境 ---


def test_a_path_alias_is_the_same_file(client, shared):
    rows = _merged(client, "n1")
    rows[0]["source_file"] = "knowledge/qa/./shared.csv"

    assert _put_merged(client, "n1", rows).status_code == 200

    assert set(_rows(shared)) == {"甲題", "乙題", "丙題", "丁題"}
    assert _questions("n1") == ["甲題", "乙題"]
    assert _questions("n2") == ["丙題", "丁題"]


def test_chained_renames_keep_each_mount_on_its_own_answer(client, shared):
    from knowledge import qa_nodes

    qa_nodes.add_qa_entry_to_node("n2", _entry("甲題"))
    qa_nodes.add_qa_entry_to_node("n2", _entry("乙題"))
    rows = _merged(client, "n1")
    rows[0]["q"] = "乙題"
    rows[1]["q"] = "新題"

    assert _put_merged(client, "n1", rows).status_code == 200

    saved = _rows(shared)
    assert saved["乙題"]["a"] == "甲答"
    assert saved["新題"]["a"] == "乙答"
    assert set(_questions("n2")) == {"丙題", "丁題", "乙題", "新題"}


def test_swapping_two_questions_keeps_mounts_on_their_answers(client, shared):
    from knowledge import qa_nodes

    qa_nodes.add_qa_entry_to_node("n2", _entry("甲題"))
    rows = _merged(client, "n1")
    rows[0]["q"], rows[1]["q"] = "乙題", "甲題"

    assert _put_merged(client, "n1", rows).status_code == 200

    saved = _rows(shared)
    assert saved["乙題"]["a"] == "甲答"
    assert saved["甲題"]["a"] == "乙答"
    assert "乙題" in _questions("n2")
    assert "甲題" not in _questions("n2")


def test_leaving_out_the_source_file_is_rejected(client, shared):
    before = shared.read_bytes()

    response = _put_merged(client, "n1", [{"q": "甲題", "a": "甲答"}])

    assert response.status_code == 422
    assert shared.read_bytes() == before


@pytest.mark.parametrize("target", ["SOUL.md", "knowledge/plain.md", "../outside.md"])
def test_saving_refuses_files_that_are_not_qa_documents(client, workspace, shared, target):
    import knowledge.doc_meta

    plain = workspace / "knowledge" / "plain.md"
    plain.write_text("一般文件\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/plain.md", "default", source_type="manual")
    soul = (workspace / "SOUL.md").read_bytes()
    rows = _merged(client, "n1")
    rows.append({"q": "新題", "a": "新答", "source_file": target})

    assert _put_merged(client, "n1", rows).status_code == 400

    assert (workspace / "SOUL.md").read_bytes() == soul
    assert plain.read_text(encoding="utf-8") == "一般文件\n"


def test_saving_a_stale_editor_is_refused(client, shared):
    from knowledge import qa_nodes

    rows = _merged(client, "n1")
    shared.write_text(_SHARED_CONTENT + "50,戊題,戊答,,,true,\n", encoding="utf-8")
    qa_nodes.sync_entries_for_source(SHARED_CSV)
    before = shared.read_bytes()

    response = _put_merged(client, "n1", rows)

    assert response.status_code == 409
    assert shared.read_bytes() == before
    assert "戊題" in _questions("n1")


def test_sending_the_same_edit_twice_is_refused(client, shared):
    rows = _merged(client, "n1")
    rows[0]["q"] = "甲題改名"

    assert _put_merged(client, "n1", rows).status_code == 200
    assert _put_merged(client, "n1", rows).status_code == 409

    assert _rows(shared)["甲題改名"]["備註"] == "甲的備註"


def test_an_unchanged_save_leaves_the_file_alone(client, workspace):
    from knowledge import qa_nodes

    source = "knowledge/qa/own.csv"
    original = "index,q,a,備註\r\n1,甲,甲答,留著\r\n2,乙,乙答,\r\n"
    doc = workspace / source
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_bytes(original.encode("utf-8"))
    import knowledge.doc_meta

    knowledge.doc_meta.upsert_document_meta(source, "default", source_type="qa")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n", "label": "N"})
    qa_nodes.update_node("n", {"qa_entries": [_entry("甲", source), _entry("乙", source)]})

    assert _put_merged(client, "n", _merged(client, "n")).status_code == 200

    assert doc.read_bytes() == original.encode("utf-8")


def test_a_repeated_question_shows_and_saves_the_same_row(client, workspace):
    from knowledge import qa_nodes

    source = "knowledge/qa/dup.csv"
    original = "index,q,a,img,display\n1,甲,舊答,old.png,true\n2,甲,新答,new.png,false\n"
    doc = _write_doc(workspace, source, original)
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n", "label": "N"})
    qa_nodes.update_node("n", {"qa_entries": qa_nodes._build_entries_for_source(source)})

    rows = _merged(client, "n")
    assert (rows[0]["a"], rows[0]["img"], rows[0]["hidden"]) == ("新答", "new.png", True)
    assert _put_merged(client, "n", rows).status_code == 200

    assert doc.read_text(encoding="utf-8") == original


def test_an_entry_the_file_no_longer_has_does_not_write_a_blank_row(client, shared):
    from knowledge import qa_nodes

    qa_nodes.add_qa_entry_to_node("n1", _entry("消失的題"))
    qa_nodes.add_qa_entry_to_node("n1", _entry("文件也沒了", "knowledge/qa/missing.csv"))
    before = shared.read_bytes()

    assert _put_merged(client, "n1", _merged(client, "n1")).status_code == 200

    assert shared.read_bytes() == before
    assert not (shared.parent / "missing.csv").exists()
    assert _questions("n1") == ["甲題", "乙題"]


def test_deleting_a_category_does_not_move_its_questions_elsewhere(client, shared):
    from knowledge import qa_nodes

    client.delete("/brain/knowledge/qa/nodes/n2")
    assert _put_merged(client, "n1", _merged(client, "n1")).status_code == 200
    qa_nodes.sync_entries_for_source(SHARED_CSV)

    assert _questions("n1") == ["甲題", "乙題"]
    assert set(_rows(shared)) == {"甲題", "乙題", "丙題", "丁題"}


def test_attaching_a_document_again_brings_all_its_questions(client, shared):
    client.delete("/brain/knowledge/qa/nodes/n1")
    client.delete("/brain/knowledge/qa/nodes/n2")

    response = client.post("/brain/knowledge/qa/nodes/adopt-source", json={"path": SHARED_CSV})

    assert response.status_code == 200
    assert _questions(response.json()["node_id"]) == ["甲題", "乙題", "丙題", "丁題"]


def test_a_mistyped_header_changes_nothing(client, shared):
    from knowledge import qa_nodes

    shared.write_text(_SHARED_CONTENT.replace("index,q,a", "index,qq,a"), encoding="utf-8")

    qa_nodes.sync_entries_for_source(SHARED_CSV)

    assert _questions("n1") == ["甲題", "乙題"]
    assert _questions("n2") == ["丙題", "丁題"]


def test_a_row_without_a_question_stays_off_the_menu(shared):
    from knowledge import qa_nodes

    shared.write_text(_SHARED_CONTENT + "50,,沒有題目的答案,,,true,\n", encoding="utf-8")

    qa_nodes.sync_entries_for_source(SHARED_CSV)

    assert "未命名問題" not in _questions("n1")


def test_editing_a_document_never_deletes_a_category(shared):
    from knowledge import qa_nodes

    shared.write_text(
        _SHARED_CONTENT.replace("丙題", "丙題改").replace("丁題", "丁題改"), encoding="utf-8",
    )

    qa_nodes.sync_entries_for_source(SHARED_CSV)

    assert qa_nodes.get_node("n2") is not None


def test_markdown_save_leaves_other_nodes_blocks_as_written(client, workspace):
    from knowledge import qa_nodes

    source = "knowledge/qa/note.md"
    other = '## 乙\n\n乙答\n\n---\n\n補充\n<!-- qa_metadata: {"img": "", "url": "", "note": "keep"} -->'
    doc = _write_doc(workspace, source, f"## 甲\n\n甲答\n\n{other}\n")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "a", "label": "A"})
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "b", "label": "B"})
    qa_nodes.update_node("a", {"qa_entries": [_entry("甲", source)]})
    qa_nodes.update_node("b", {"qa_entries": [_entry("乙", source)]})
    rows = _merged(client, "a")
    rows[0]["a"] = "甲的新答"

    assert _put_merged(client, "a", rows).status_code == 200

    content = doc.read_text(encoding="utf-8")
    assert "甲的新答" in content
    assert other in content


def test_a_failed_write_puts_every_file_back(client, workspace, monkeypatch):
    from knowledge import qa_merged, qa_nodes

    first = _write_doc(workspace, "knowledge/qa/a.csv", "index,q,a\n1,甲,甲答\n")
    second = _write_doc(workspace, "knowledge/qa/b.csv", "index,q,a\n1,乙,乙答\n")
    client.post("/brain/knowledge/qa/nodes", json={"node_id": "n", "label": "N"})
    entries = [_entry("甲", "knowledge/qa/a.csv"), _entry("乙", "knowledge/qa/b.csv")]
    qa_nodes.update_node("n", {"qa_entries": entries})
    before = first.read_bytes(), second.read_bytes()
    rows = _merged(client, "n")
    rows[0]["a"], rows[1]["a"] = "改甲", "改乙"
    real_save = qa_merged.save_workspace_document

    def fail_on_second(path, content, project_id):
        if path.endswith("b.csv"):
            raise OSError("disk full")
        return real_save(path, content, project_id)

    monkeypatch.setattr(qa_merged, "save_workspace_document", fail_on_second)

    with pytest.raises(OSError):
        _put_merged(client, "n", rows)

    assert (first.read_bytes(), second.read_bytes()) == before
    assert _questions("n") == ["甲", "乙"]

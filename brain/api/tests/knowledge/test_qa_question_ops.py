"""Direct single-question edits (save_question) and atomic batch category moves (move_qa_entries)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import knowledge.workspace
from config import get_settings
from knowledge import qa_nodes
from knowledge.doc_meta import upsert_document_meta
from knowledge.qa_entry_moves import QaEntryMoveError, move_qa_entries
from knowledge.qa_merged import MergedSaveError, read_question, save_question
from knowledge.qa_questions import list_all_questions
from main import app


@pytest.fixture
def workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    monkeypatch.setattr(knowledge.workspace, "get_workspace_root", lambda project_id="default": root)
    knowledge.workspace.ensure_workspace_scaffold()
    return root


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> TestClient:
    import routes.knowledge_qa

    reindexed: list[str] = []
    monkeypatch.setattr(routes.knowledge_qa, "schedule_reindex", lambda project_id="default": reindexed.append(project_id))
    test_client = TestClient(
        app,
        headers={"X-Internal-Token": get_settings().gateway_internal_token},
    )
    test_client.reindexed = reindexed  # type: ignore[attr-defined]
    return test_client


def _write_qa(root: Path, relative: str, content: str) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    upsert_document_meta(relative, "default", source_type="qa")
    return relative


def _file_hash(root: Path, relative: str) -> str:
    return knowledge.workspace.content_hash((root / relative).read_text(encoding="utf-8-sig"))


@pytest.mark.parametrize(
    ("relative", "initial_content"),
    [
        (
            "knowledge/qa/faq.csv",
            "index,q,a,img,url,display\n"
            "1,營業時間？,九點開門,,https://example.com/hours,true\n"
            "2,停車資訊？,大樓後方,map.png,,true\n",
        ),
        (
            "knowledge/qa/faq.md",
            '## 營業時間？\n\n九點開門\n<!-- qa_metadata: {"img": "", "url": "https://example.com/hours"} -->\n\n'
            '## 停車資訊？\n\n大樓後方\n<!-- qa_metadata: {"img": "map.png", "url": ""} -->\n',
        ),
    ],
    ids=["csv", "md"],
)
def test_save_question_updates_answer_and_renames_on_all_mounted_categories_and_syncs_hidden(
    workspace: Path, relative: str, initial_content: str,
) -> None:
    source = _write_qa(workspace, relative, initial_content)
    qa_nodes.create_node("cat_a", "分類甲")
    qa_nodes.create_node("cat_b", "分類乙")
    for cid in ("cat_a", "cat_b"):
        qa_nodes.add_qa_entry_to_node(cid, {"question": "營業時間？", "source_path": source}, "default")
    qa_nodes.add_qa_entry_to_node("cat_b", {"question": "停車資訊？", "source_path": source}, "default")

    base_hash = _file_hash(workspace, relative)
    result = save_question(
        source,
        "營業時間？",
        "週末營業時間？",
        "十點開門",
        "default",
        img="weekend.png",
        url="https://example.com/weekend",
        hidden=True,
        base_hash=base_hash,
    )

    assert result["question"] == {
        "q": "週末營業時間？",
        "a": "十點開門",
        "img": "weekend.png",
        "url": "https://example.com/weekend",
        "hidden": True,
    }
    assert result["content_hash"] == _file_hash(workspace, relative)
    assert result["content_hash"] != base_hash
    # 同檔另一題原封不動
    assert read_question(source, "停車資訊？", "default")["a"] == "大樓後方"

    expected_updated = {
        "question": "週末營業時間？",
        "source_path": source,
        "hidden": True,
        "image_id": "weekend.png",
    }
    assert qa_nodes.get_node("cat_a", "default")["qa_entries"] == [expected_updated]
    assert qa_nodes.get_node("cat_b", "default")["qa_entries"] == [
        expected_updated,
        {
            "question": "停車資訊？",
            "source_path": source,
            "hidden": False,
            "image_id": "map.png",
        },
    ]


def test_save_question_rejects_mismatched_base_hash_with_409_and_leaves_file_unchanged(workspace: Path) -> None:
    source = _write_qa(workspace, "knowledge/qa/faq.csv", "q,a\n題目一,答案一\n")
    before = (workspace / source).read_bytes()

    with pytest.raises(MergedSaveError) as exc_info:
        save_question(
            source,
            "題目一",
            "題目一改",
            "答案一改",
            "default",
            base_hash="stale-hash-00000",
        )

    assert exc_info.value.status == 409
    assert "被改過了" in exc_info.value.detail
    assert (workspace / source).read_bytes() == before


@pytest.mark.parametrize("new_answer", ["答案二", "完全不同的答案"], ids=["same-answer", "different-answer"])
def test_save_question_rejects_renaming_to_existing_question_in_same_file_with_400(
    workspace: Path, new_answer: str,
) -> None:
    source = _write_qa(
        workspace,
        "knowledge/qa/faq.md",
        "## 題目一\n\n答案一\n\n## 題目二\n\n答案二\n",
    )
    before = (workspace / source).read_bytes()

    with pytest.raises(MergedSaveError) as exc_info:
        save_question(source, "題目一", "題目二", new_answer, "default")

    assert exc_info.value.status == 400
    assert (workspace / source).read_bytes() == before


def test_save_question_route_succeeds_and_rejects_invisible_vendor_source(
    client: TestClient, workspace: Path,
) -> None:
    source = _write_qa(workspace, "knowledge/qa/off_menu.csv", "q,a\n未分類題目,原本答案\n")
    questions = list_all_questions("default")["questions"]
    assert questions[0]["content_hash"] == _file_hash(workspace, source)

    ok_res = client.put(
        "/brain/knowledge/qa/questions",
        json={
            "project_id": "default",
            "source_path": source,
            "original_q": "未分類題目",
            "q": "未分類題目（已更新）",
            "a": "更新後的答案",
            "img": "",
            "url": "https://example.com",
            "hidden": True,
            "base_hash": questions[0]["content_hash"],
        },
    )
    assert ok_res.status_code == 200, ok_res.text
    assert ok_res.json()["question"]["q"] == "未分類題目（已更新）"
    assert ok_res.json()["question"]["a"] == "更新後的答案"
    assert ok_res.json()["question"]["hidden"] is True
    assert client.reindexed == ["default"]  # type: ignore[attr-defined]

    conflict_res = client.put(
        "/brain/knowledge/qa/questions",
        json={
            "project_id": "default",
            "source_path": source,
            "original_q": "未分類題目（已更新）",
            "q": "再次修改",
            "a": "不會寫入",
            "base_hash": questions[0]["content_hash"],
        },
    )
    assert conflict_res.status_code == 409

    # 廠商不可修改隱藏資料夾或工作區根目錄等看不到的來源
    hidden_doc = workspace / "knowledge" / ".hidden" / "secret.md"
    hidden_doc.parent.mkdir(parents=True, exist_ok=True)
    hidden_doc.write_text("## 秘密\n\n內容\n", encoding="utf-8")
    before_secret = hidden_doc.read_bytes()

    vendor_res = client.put(
        "/brain/knowledge/qa/questions",
        headers={"X-OpenVMan-Vendor": "1"},
        json={
            "project_id": "default",
            "source_path": "knowledge/.hidden/secret.md",
            "original_q": "秘密",
            "q": "秘密",
            "a": "被竄改",
        },
    )
    assert vendor_res.status_code == 403
    assert hidden_doc.read_bytes() == before_secret


def test_move_qa_entries_moves_from_a_to_end_of_b_without_recording_detached(workspace: Path) -> None:
    source = _write_qa(workspace, "knowledge/qa/faq.md", "## 甲題\n\n甲答\n\n## 乙題\n\n乙答\n")
    qa_nodes.create_node("a", "分類A")
    qa_nodes.create_node("b", "分類B")
    qa_nodes.add_qa_entry_to_node(
        "a",
        {"question": "甲題", "source_path": source, "hidden": True, "image_id": "pic.png"},
        "default",
    )
    qa_nodes.add_qa_entry_to_node(
        "b",
        {"question": "乙題", "source_path": source, "hidden": False, "image_id": None},
        "default",
    )

    result = move_qa_entries(
        "b",
        [{"question": "甲題", "source_path": source, "from_node_ids": ["a"]}],
        "default",
    )

    assert result["from"][0]["node_id"] == "a"
    assert result["from"][0]["qa_entries"] == []
    assert [e["question"] for e in result["to"]["qa_entries"]] == ["乙題", "甲題"]
    assert result["to"]["qa_entries"][1] == {
        "question": "甲題",
        "source_path": source,
        "hidden": True,
        "image_id": "pic.png",
    }
    raw_nodes = qa_nodes._load_nodes_data("default")
    assert raw_nodes.get("detached", {}) == {}


def test_move_qa_entries_moves_from_one_category_of_multi_mounted_question_leaving_others_intact(
    workspace: Path,
) -> None:
    source = _write_qa(workspace, "knowledge/qa/faq.md", "## 共用題\n\n答案\n")
    for cid, label in (("a", "分類A"), ("b", "分類B"), ("c", "分類C")):
        qa_nodes.create_node(cid, label)
    for cid in ("a", "b"):
        qa_nodes.add_qa_entry_to_node(cid, {"question": "共用題", "source_path": source}, "default")

    move_qa_entries(
        "c",
        [{"question": "共用題", "source_path": source, "from_node_ids": ["a"]}],
        "default",
    )

    assert qa_nodes.get_node("a", "default")["qa_entries"] == []
    assert [e["question"] for e in qa_nodes.get_node("b", "default")["qa_entries"]] == ["共用題"]
    assert [e["question"] for e in qa_nodes.get_node("c", "default")["qa_entries"]] == ["共用題"]


def test_move_qa_entries_mounts_uncategorized_question_from_source(workspace: Path) -> None:
    source = _write_qa(
        workspace,
        "knowledge/qa/off.csv",
        "q,a,img,url,display\n未分類題,答案,chart.png,,false\n",
    )
    qa_nodes.create_node("target", "目標分類")

    result = move_qa_entries(
        "target",
        [{"question": "未分類題", "source_path": source, "from_node_ids": []}],
        "default",
    )

    assert result["from"] == []
    assert result["to"]["qa_entries"] == [
        {
            "question": "未分類題",
            "source_path": source,
            "hidden": True,
            "image_id": "chart.png",
        }
    ]


def test_move_qa_entries_batch_clash_is_all_or_nothing_and_lists_clashing_question(workspace: Path) -> None:
    source = _write_qa(
        workspace,
        "knowledge/qa/faq.md",
        "## 第一題\n\n答1\n\n## 第二題\n\n答2\n\n## 第三題\n\n答3\n",
    )
    qa_nodes.create_node("a", "分類A")
    qa_nodes.create_node("b", "分類B")
    for q in ("第一題", "第二題", "第三題"):
        qa_nodes.add_qa_entry_to_node("a", {"question": q, "source_path": source}, "default")
    # 目標分類已經有「第二題」
    qa_nodes.add_qa_entry_to_node("b", {"question": "第二題", "source_path": ""}, "default")

    nodes_file = workspace / "knowledge" / ".qa_nodes.json"
    before_bytes = nodes_file.read_bytes()

    with pytest.raises(QaEntryMoveError) as exc_info:
        move_qa_entries(
            "b",
            [
                {"question": "第一題", "source_path": source, "from_node_ids": ["a"]},
                {"question": "第二題", "source_path": source, "from_node_ids": ["a"]},
                {"question": "第三題", "source_path": source, "from_node_ids": ["a"]},
            ],
            "default",
        )

    assert exc_info.value.status == 400
    assert "「第二題」" in exc_info.value.detail
    assert "在目標分類已經有相同的題目" in exc_info.value.detail
    assert nodes_file.read_bytes() == before_bytes


def test_move_qa_entries_keeps_target_position_when_target_is_in_from_node_ids(workspace: Path) -> None:
    source = _write_qa(
        workspace,
        "knowledge/qa/faq.md",
        "## 第一題\n\n答1\n\n## 第二題\n\n答2\n\n## 第三題\n\n答3\n",
    )
    qa_nodes.create_node("a", "分類A")
    qa_nodes.create_node("b", "分類B")
    qa_nodes.add_qa_entry_to_node("a", {"question": "第一題", "source_path": source}, "default")
    for q in ("第一題", "第二題", "第三題"):
        qa_nodes.add_qa_entry_to_node("b", {"question": q, "source_path": source}, "default")

    result = move_qa_entries(
        "b",
        [{"question": "第一題", "source_path": source, "from_node_ids": ["a", "b"]}],
        "default",
    )

    assert qa_nodes.get_node("a", "default")["qa_entries"] == []
    # 「第一題」原本在 b 的第一個位置，不會被移到最後面
    assert [e["question"] for e in result["to"]["qa_entries"]] == ["第一題", "第二題", "第三題"]


def test_move_questions_route_succeeds_and_fails_atomically(client: TestClient, workspace: Path) -> None:
    source = _write_qa(workspace, "knowledge/qa/faq.md", "## 題A\n\n答A\n\n## 題B\n\n答B\n")
    qa_nodes.create_node("a", "分類A")
    qa_nodes.create_node("b", "分類B")
    qa_nodes.add_qa_entry_to_node("a", {"question": "題A", "source_path": source}, "default")
    qa_nodes.add_qa_entry_to_node("b", {"question": "題B", "source_path": source}, "default")

    ok_res = client.post(
        "/brain/knowledge/qa/questions/move",
        json={
            "project_id": "default",
            "to_node_id": "b",
            "items": [{"question": "題A", "source_path": source, "from_node_ids": ["a"]}],
        },
    )
    assert ok_res.status_code == 200, ok_res.text
    assert [e["question"] for e in ok_res.json()["to"]["qa_entries"]] == ["題B", "題A"]
    assert ok_res.json()["from"][0]["qa_entries"] == []

    nodes_file = workspace / "knowledge" / ".qa_nodes.json"
    before_bytes = nodes_file.read_bytes()
    fail_res = client.post(
        "/brain/knowledge/qa/questions/move",
        json={
            "project_id": "default",
            "to_node_id": "b",
            "items": [{"question": "題A", "source_path": source, "from_node_ids": ["a"]}],
        },
    )
    assert fail_res.status_code == 404
    assert "「題A」不在原本的分類裡" in fail_res.json()["detail"]
    assert nodes_file.read_bytes() == before_bytes


def _mount(node_id: str, question: str, source: str) -> None:
    qa_nodes.add_qa_entry_to_node(
        node_id, {"question": question, "source_path": source},
    )


def _save_category(client: TestClient, node_id: str, **updates: str) -> None:
    endpoint = f"/brain/knowledge/qa/nodes/{node_id}/merged"
    response = client.get(endpoint)
    assert response.status_code == 200
    rows = response.json()
    rows[0].update(updates)
    saved = client.put(endpoint, json=rows)
    assert saved.status_code == 200, saved.text


def _questions_in(node_id: str) -> list[str]:
    return [entry["question"] for entry in qa_nodes.get_node(node_id)["qa_entries"]]


def test_single_save_preserves_csv_index_and_other_rows(workspace: Path) -> None:
    before = (
        "index,q,a,img,url,display,備註\n"
        "100,甲,答甲,,,true,x1\n"
        "300,丙,答丙,,,false,x3\n"
        "200,乙,答乙,,,true,x2\n"
    )
    source = _write_qa(workspace, "knowledge/qa/faq.csv", before)

    save_question(source, "丙", "新丙", "新答", img="map.png", url="https://example.com", hidden=True)

    assert (workspace / source).read_text(encoding="utf-8") == before.replace(
        "丙,答丙,,,false", "新丙,新答,map.png,https://example.com,false",
    )


def test_move_after_shared_question_rename_keeps_target_entry(
    client: TestClient, workspace: Path,
) -> None:
    source = _write_qa(workspace, "knowledge/qa/faq.md", "## 舊題\n\n答案\n\n## 另一題\n\n答二\n")
    for node in ("a", "b"):
        qa_nodes.create_node(node, node)
        _mount(node, "舊題", source)
    _mount("b", "另一題", source)
    _save_category(client, "a", q="新題")
    assert _questions_in("b") == ["新題", "另一題"]

    response = client.post("/brain/knowledge/qa/questions/move", json={
        "to_node_id": "b",
        "items": [{"question": "新題", "source_path": source, "from_node_ids": ["a"]}],
    })

    assert response.status_code == 200, response.text
    assert _questions_in("a") == []
    assert _questions_in("b") == ["新題", "另一題"]


def test_batch_move_preserves_existing_target_entries(workspace: Path) -> None:
    source = _write_qa(workspace, "knowledge/qa/faq.csv", "q,a\n共用題,答一\n原有題,答二\n待移題,答三\n")
    for node in ("a", "b"):
        qa_nodes.create_node(node, node)
        _mount(node, "共用題", source)
    _mount("a", "待移題", source)
    _mount("b", "原有題", source)
    original_target = qa_nodes.get_node("b")["qa_entries"]

    result = move_qa_entries("b", [
        {"question": "共用題", "source_path": source, "from_node_ids": ["a"]},
        {"question": "原有題", "source_path": source, "from_node_ids": ["b"]},
        {"question": "待移題", "source_path": source, "from_node_ids": ["a"]},
    ])

    assert _questions_in("a") == []
    assert _questions_in("b") == ["共用題", "原有題", "待移題"]
    assert result["to"]["qa_entries"][:2] == original_target


@pytest.mark.parametrize("vendor", [False, True], ids=["admin", "vendor"])
def test_move_refuses_to_mount_non_qa_document(
    client: TestClient, workspace: Path, vendor: bool,
) -> None:
    source = "knowledge/notes.md"
    (workspace / source).write_text("## 公司簡介\n\n一般文件內容\n", encoding="utf-8")
    upsert_document_meta(source, "default", source_type="upload")
    qa_nodes.create_node("a", "分類")
    before = qa_nodes.nodes_snapshot()
    headers = {"X-OpenVMan-Vendor": "1"} if vendor else {}

    move = client.post("/brain/knowledge/qa/questions/move", headers=headers, json={
        "to_node_id": "a",
        "items": [{"question": "公司簡介", "source_path": source, "from_node_ids": []}],
    })
    add = client.post("/brain/knowledge/qa/nodes/a/entries", headers=headers, json={
        "question": "公司簡介", "source_path": source,
    })

    assert move.status_code == add.status_code == 400
    assert move.json()["detail"] == add.json()["detail"] == f"{source} 不是 QA 文件"
    assert qa_nodes.nodes_snapshot() == before


@pytest.mark.parametrize("vendor", [False, True], ids=["admin", "vendor"])
@pytest.mark.parametrize("mounted", [False, True], ids=["unmounted", "mounted"])
def test_single_save_refuses_non_qa_document(
    client: TestClient, workspace: Path, vendor: bool, mounted: bool,
) -> None:
    source = "knowledge/notes.md"
    original = "## 公司簡介\n\n一般文件內容\n"
    (workspace / source).write_text(original, encoding="utf-8")
    upsert_document_meta(source, "default", source_type="upload")
    if mounted:
        qa_nodes.create_node("a", "分類")
        _mount("a", "公司簡介", source)
    before = qa_nodes.nodes_snapshot()
    headers = {"X-OpenVMan-Vendor": "1"} if vendor else {}

    response = client.put("/brain/knowledge/qa/questions", headers=headers, json={
        "source_path": source, "original_q": "公司簡介", "q": "改題目", "a": "改答案",
    })

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == f"{source} 不是 QA 文件"
    assert (workspace / source).read_text(encoding="utf-8") == original
    assert qa_nodes.nodes_snapshot() == before


def test_save_category_mounts_other_questions_from_same_file(
    client: TestClient, workspace: Path,
) -> None:
    source = _write_qa(workspace, "knowledge/qa/faq.md", "## 甲\n\n答甲\n\n## 乙\n\n答乙\n")
    qa_nodes.create_node("a", "分類")
    _mount("a", "甲", source)

    _save_category(client, "a", a="更新的答甲")

    assert _questions_in("a") == ["甲", "乙"]


def test_single_save_leaves_same_file_questions_uncategorized(workspace: Path) -> None:
    source = _write_qa(workspace, "knowledge/qa/faq.md", "## 甲\n\n答甲\n\n## 乙\n\n答乙\n")
    qa_nodes.create_node("a", "分類")
    _mount("a", "甲", source)

    save_question(source, "乙", "新乙", "新答乙")

    assert _questions_in("a") == ["甲"]
    assert read_question(source, "新乙", "default")["a"] == "新答乙"


def test_single_save_keeps_category_order_that_differs_from_file_order(
    workspace: Path,
) -> None:
    source = _write_qa(
        workspace,
        "knowledge/qa/faq.csv",
        "index,q,a\n1,甲,答甲\n2,乙,答乙\n3,丙,答丙\n4,丁,答丁\n",
    )
    qa_nodes.create_node("a", "分類")
    _mount("a", "甲", source)
    _mount("a", "丙", source)
    move_qa_entries("a", [{"question": "乙", "source_path": source, "from_node_ids": []}])
    assert _questions_in("a") == ["甲", "丙", "乙"]

    save_question(source, "丁", "丁", "新答丁")

    assert _questions_in("a") == ["甲", "丙", "乙"]
    assert read_question(source, "丁", "default")["a"] == "新答丁"


def test_vendor_move_checks_every_source_before_writing(
    client: TestClient, workspace: Path,
) -> None:
    visible = _write_qa(workspace, "knowledge/qa/faq.md", "## 可見題\n\n答案\n")
    restricted = _write_qa(workspace, "knowledge/graphify-out/private.md", "## 內部題\n\n答案\n")
    for node in ("a", "b"):
        qa_nodes.create_node(node, node)
    _mount("a", "可見題", visible)
    _mount("a", "內部題", restricted)
    before = qa_nodes.nodes_snapshot()

    response = client.post(
        "/brain/knowledge/qa/questions/move",
        headers={"X-OpenVMan-Vendor": "1"},
        json={"to_node_id": "b", "items": [
            {"question": "可見題", "source_path": visible, "from_node_ids": ["a"]},
            {"question": "內部題", "source_path": restricted, "from_node_ids": ["a"]},
        ]},
    )

    assert response.status_code == 403, response.text
    assert qa_nodes.nodes_snapshot() == before


def test_vendor_move_filters_source_and_target_responses(
    client: TestClient, workspace: Path,
) -> None:
    visible = _write_qa(workspace, "knowledge/qa/faq.md", "## 可見題\n\n答案\n")
    restricted = _write_qa(workspace, "knowledge/graphify-out/private.md", "## 內部題\n\n答案\n")
    for node in ("a", "b"):
        qa_nodes.create_node(node, node)
        _mount(node, "內部題", restricted)
    _mount("a", "可見題", visible)

    response = client.post(
        "/brain/knowledge/qa/questions/move",
        headers={"X-OpenVMan-Vendor": "1"},
        json={"to_node_id": "b", "items": [
            {"question": "可見題", "source_path": visible, "from_node_ids": ["a"]},
        ]},
    )

    assert response.status_code == 200, response.text
    assert [entry["question"] for entry in response.json()["to"]["qa_entries"]] == ["可見題"]
    assert response.json()["from"][0]["qa_entries"] == []
    assert _questions_in("a") == ["內部題"]
    assert _questions_in("b") == ["內部題", "可見題"]


def test_renaming_detached_question_keeps_it_off_menu_after_category_save(
    client: TestClient, workspace: Path,
) -> None:
    source = _write_qa(workspace, "knowledge/qa/faq.md", "## 甲\n\n答甲\n\n## 乙\n\n答乙\n")
    qa_nodes.create_node("a", "分類")
    for question in ("甲", "乙"):
        _mount("a", question, source)
    qa_nodes.remove_qa_entry_from_node("a", "乙", source_path=source)

    save_question(source, "乙", "新乙", "新答乙")
    row = next(row for row in list_all_questions()["questions"] if row["question"] == "新乙")
    assert row["off_menu"] == "detached"
    _save_category(client, "a", a="更新答甲")

    assert _questions_in("a") == ["甲"]


@pytest.mark.parametrize("vendor", [False, True], ids=["admin", "vendor"])
def test_single_save_reports_missing_source_in_chinese(client: TestClient, vendor: bool) -> None:
    headers = {"X-OpenVMan-Vendor": "1"} if vendor else {}
    response = client.put("/brain/knowledge/qa/questions", headers=headers, json={
        "source_path": "", "original_q": "原題", "q": "新題", "a": "答案",
    })
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "請指定來源文件"

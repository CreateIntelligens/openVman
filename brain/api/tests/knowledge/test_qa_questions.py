"""The flat "所有題目" list: one row per question, with categories and states."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import knowledge.workspace
from knowledge import qa_nodes
from knowledge.doc_meta import upsert_document_meta
from knowledge.qa_questions import list_all_questions


@pytest.fixture
def workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    monkeypatch.setattr(knowledge.workspace, "get_workspace_root", lambda project_id="default": root)
    knowledge.workspace.ensure_workspace_scaffold()
    return root


def _write(root: Path, relative: str, content: str, language: str | None = None) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))
    upsert_document_meta(relative, "default", source_type="qa", **({"language": language} if language else {}))
    return relative


def _mount(node_id: str, source: str, question: str) -> None:
    qa_nodes.add_qa_entry_to_node(node_id, {"question": question, "source_path": source}, "default")


def _rows() -> dict[str, dict]:
    return {row["question"]: row for row in list_all_questions("default")["questions"]}


@pytest.fixture
def menu(workspace: Path) -> Path:
    csv = _write(
        workspace,
        "knowledge/qa/faq.csv",
        'q,a,img,url,display,language\r\n'
        '營業時間？,九點開門,,https://example.com/hours,,zh\r\n'
        'Parking?,Behind the building,map.png,,false,en\r\n'
        '"多行\r\n題目？",有答案,,,,\r\n'
        '沒答案的題目,,,,,\r\n'
        '沒掛上的題目,答案,,,,\r\n'
        '拿下來的題目,答案,,,,\r\n',
        language="zh",
    )
    md = _write(workspace, "knowledge/qa/guide.md", "## Hello?\n\nWorld\n", language="en")
    qa_nodes.create_node("zh", "中文")
    qa_nodes.create_node("svc", "服務", parent_ids=["zh"])
    qa_nodes.create_node("en", "English", hidden=True)
    for question in ("營業時間？", "Parking?", "多行\n題目？", "沒答案的題目", "拿下來的題目"):
        _mount("svc", csv, question)
    _mount("en", csv, "Parking?")
    _mount("en", md, "Hello?")
    qa_nodes.add_qa_entry_to_node("svc", {"question": "只在選單上的題目"}, "default")
    qa_nodes.remove_qa_entry_from_node("svc", "拿下來的題目", "default", source_path=csv)
    return workspace


def test_a_question_on_two_categories_is_one_row_with_both_in_tree_order(menu: Path):
    result = list_all_questions("default")
    parking = [row for row in result["questions"] if row["question"] == "Parking?"]

    assert len(parking) == 1
    assert parking[0]["category_ids"] == ["svc", "en"]
    paths = {category["node_id"]: category["path"] for category in result["categories"]}
    assert paths["svc"] == ["中文", "服務"]


def test_each_row_carries_the_answer_link_image_and_source(menu: Path):
    rows = _rows()

    assert rows["營業時間？"]["answer"] == "九點開門"
    assert rows["營業時間？"]["url"] == "https://example.com/hours"
    assert rows["Parking?"]["image"] == "map.png"
    assert rows["Parking?"]["hidden_in_file"] is True
    assert rows["營業時間？"]["source"] == {"kind": "file", "path": "knowledge/qa/faq.csv", "label": "faq.csv"}


def test_languages_come_from_the_row_label_then_the_document(menu: Path):
    rows = _rows()

    assert rows["Parking?"]["language"] == "en"
    assert rows["營業時間？"]["language"] == "zh"
    # 沒標語言的列跟著文件的語言。
    assert rows["沒答案的題目"]["language"] == "zh"
    assert rows["Hello?"]["language"] == "en"
    assert rows["只在選單上的題目"]["language"] is None


def test_a_question_with_windows_line_breaks_still_counts_as_on_the_menu(menu: Path):
    row = next(row for row in list_all_questions("default")["questions"] if row["question"].startswith("多行"))

    assert row["category_ids"] == ["svc"]
    assert row["off_menu"] is None


def test_questions_off_the_menu_say_whether_they_were_taken_off_or_never_put_on(menu: Path):
    rows = _rows()

    assert rows["拿下來的題目"]["off_menu"] == "detached"
    assert rows["沒掛上的題目"]["off_menu"] == "never"
    assert rows["沒掛上的題目"]["category_ids"] == []
    assert rows["營業時間？"]["off_menu"] is None


def test_hidden_categories_and_missing_answers_are_separate_states(menu: Path):
    rows = _rows()

    # 只掛在隱藏分類的題目，訪客看不到；還掛在別的顯示中分類就看得到。
    assert rows["Hello?"]["category_hidden"] is True
    assert rows["Parking?"]["category_hidden"] is False
    assert rows["沒答案的題目"]["no_answer"] is True
    assert rows["營業時間？"]["no_answer"] is False


def test_menu_only_questions_are_listed_by_category_and_do_not_count_as_unanswered(menu: Path):
    row = _rows()["只在選單上的題目"]

    assert row["source"] == {"kind": "menu_only", "path": "", "label": "只在選單上"}
    assert row["category_ids"] == ["svc"]
    assert row["no_answer"] is False


def test_typed_in_questions_say_so_instead_of_a_file_name(workspace: Path):
    source = _write(workspace, "knowledge/qa/manual_svc_1.md", "## 自己加的？\n\n好\n")
    qa_nodes.create_node("svc", "服務")
    _mount("svc", source, "自己加的？")

    row = _rows()["自己加的？"]

    assert row["source"]["kind"] == "manual"
    assert row["source"]["label"] == "自己輸入"


def test_a_project_without_questions_returns_empty_lists(workspace: Path):
    assert list_all_questions("default") == {"categories": [], "questions": []}

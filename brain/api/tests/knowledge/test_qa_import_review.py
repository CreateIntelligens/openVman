"""Mixed-language QA tables and the notes shown after an import."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import knowledge.normalizer
import knowledge.workspace
from knowledge import qa_nodes
from knowledge.raw_import import commit_raw_documents

MIXED = (
    "問題,答案\n"
    "營業時間是幾點？,早上九點到下午六點。\n"
    "可以停車嗎？,後方有收費停車場。\n"
    "What are the opening hours?,From nine in the morning to six in the evening.\n"
    "Is there parking?,There is a paid car park behind the building.\n"
    "¿Cuál es el horario?,De nueve de la mañana a seis de la tarde.\n"
)
CHINESE = "問題,答案\n營業時間是幾點？,早上九點到下午六點。\n可以停車嗎？,後方有收費停車場。\n"


@pytest.fixture
def workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    monkeypatch.setattr(knowledge.workspace, "get_workspace_root", lambda project_id="default": root)
    knowledge.workspace.ensure_workspace_scaffold()
    monkeypatch.setattr(knowledge.normalizer, "normalize_to_markdown", lambda text: f"LLM_CLEANED\n{text}")
    return root


def _raw(workspace: Path, name: str, content: str) -> None:
    path = workspace / "raw" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _import(workspace: Path, name: str, content: str) -> dict:
    _raw(workspace, name, content)
    summary = commit_raw_documents("default")
    assert name in summary["results"], summary["skip_reasons"]
    return summary["results"][name]


def _questions_under(label: str) -> dict[str, set[str]]:
    """Questions of each child category of the first-level node ``label``."""
    nodes = qa_nodes.list_nodes("default")
    parent = next(node_id for node_id, node in nodes.items() if node["label"] == label and not node["parent_ids"])
    return {
        nodes[child]["label"]: {entry["question"] for entry in nodes[child].get("qa_entries", [])}
        for child in nodes[parent]["child_ids"]
    }


def _languages():
    qa_nodes.create_node("zh", "中文")
    qa_nodes.create_node("en", "English")
    qa_nodes.create_node("es", "Español")


def test_a_mixed_table_is_split_into_its_language_categories(workspace: Path):
    _languages()

    result = _import(workspace, "faq.csv", MIXED)

    assert result["target"] == "knowledge/qa/faq.csv"
    assert result["languages"] == {"zh": 2, "en": 2, "es": 1}
    assert _questions_under("中文") == {"faq": {"營業時間是幾點？", "可以停車嗎？"}}
    assert _questions_under("English") == {"faq": {"What are the opening hours?", "Is there parking?"}}
    assert _questions_under("Español") == {"faq": {"¿Cuál es el horario?"}}
    stored = (workspace / "knowledge" / "qa" / "faq.csv").read_text(encoding="utf-8").splitlines()
    assert stored[0].endswith("language")
    assert stored[3].endswith(",en")
    assert "notes" not in result


def test_a_single_language_table_is_imported_as_before(workspace: Path):
    _languages()

    result = _import(workspace, "faq.csv", CHINESE)

    assert result["target"] == "knowledge/qa/faq.md"
    assert "languages" not in result
    assert result["qa_parent_label"] == "中文"
    assert "language" not in (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8")


def test_a_mixed_table_stays_in_one_category_when_the_project_has_no_language_categories(workspace: Path):
    result = _import(workspace, "faq.csv", MIXED)

    nodes = qa_nodes.list_nodes("default")
    assert [node["label"] for node in nodes.values()] == ["faq"]
    assert result["question_count"] == 5
    assert "notes" not in result


def test_a_language_without_a_category_stays_at_the_top_and_is_reported(workspace: Path):
    qa_nodes.create_node("zh", "中文")

    result = _import(workspace, "faq.csv", MIXED)

    top = [node for node in qa_nodes.list_nodes("default").values() if not node["parent_ids"]]
    assert sorted(node["label"] for node in top) == ["faq", "中文"]
    assert any("還沒有「English」分類，English 的 2 題先放在最上層的「faq」" in note for note in result["notes"])
    assert any("還沒有「Español」分類" in note for note in result["notes"])


def test_a_single_language_file_without_its_category_is_reported(workspace: Path):
    qa_nodes.create_node("zh", "中文")

    result = _import(workspace, "faq.csv", "q,a\nWhat are the opening hours?,From nine to six.\n")

    assert any("還沒有「English」分類，這份先放在最上層" in note for note in result["notes"])


def test_labels_people_wrote_are_kept_and_blanks_are_filled(workspace: Path):
    _languages()
    table = "q,a,語言\nWhat are the opening hours?,From nine to six.,es\n可以停車嗎？,後方有收費停車場。,\n"

    result = _import(workspace, "faq.csv", table)

    rows = (workspace / "knowledge" / "qa" / "faq.csv").read_text(encoding="utf-8").splitlines()
    assert rows[1].endswith(",es")
    assert rows[2].endswith(",zh")
    assert result["languages"] == {"es": 1, "zh": 1}
    assert _questions_under("Español") == {"faq": {"What are the opening hours?"}}


def test_an_unknown_language_label_is_kept_and_reported(workspace: Path):
    _languages()
    table = "q,a,language\n營業時間是幾點？,早上九點到下午六點。,法文\nIs there parking?,Behind the building.,en\n"

    result = _import(workspace, "faq.csv", table)

    rows = (workspace / "knowledge" / "qa" / "faq.csv").read_text(encoding="utf-8").splitlines()
    assert rows[1].endswith(",法文")
    assert any("語言欄看不懂：「法文」1 題" in note for note in result["notes"])


def test_importing_the_same_mixed_table_twice_adds_no_categories(workspace: Path):
    _languages()
    _import(workspace, "faq.csv", MIXED)
    english = next(
        node_id for node_id, node in qa_nodes.list_nodes("default").items()
        if node["label"] == "faq" and node["parent_ids"] == ["en"]
    )
    before = set(qa_nodes.list_nodes("default"))

    result = _import(workspace, "faq.csv", MIXED + "Where is the toilet?,Next to the lift.\n")

    assert set(qa_nodes.list_nodes("default")) == before
    assert result["added"] == 1
    english_questions = {e["question"] for e in qa_nodes.list_nodes("default")[english]["qa_entries"]}
    assert "Where is the toilet?" in english_questions


def test_excel_mixed_tables_are_split_too(workspace: Path):
    import openpyxl

    _languages()
    book = openpyxl.Workbook()
    sheet = book.active
    for row in [line.split(",") for line in MIXED.strip().splitlines()]:
        sheet.append(row)
    (workspace / "raw").mkdir(parents=True, exist_ok=True)
    book.save(workspace / "raw" / "faq.xlsx")

    summary = commit_raw_documents("default")

    assert summary["results"]["faq.xlsx"]["languages"] == {"zh": 2, "en": 2, "es": 1}
    assert _questions_under("English") == {"faq": {"What are the opening hours?", "Is there parking?"}}


def test_notes_name_ignored_columns_missing_answers_and_images(workspace: Path):
    table = "問題,答案,來源檔,備註,圖片\n營業時間是幾點？,早上九點。,manual.pdf,,\n可以停車嗎？,,manual.pdf,,map.png\n"

    result = _import(workspace, "faq.csv", table)

    notes = result["notes"]
    assert "這些欄位沒有讀進去：來源檔、備註" in notes
    assert any("「可以停車嗎？」沒有答案" in note for note in notes)
    assert any("1 題的圖片找不到（map.png）" in note for note in notes)


def test_a_table_without_question_columns_says_why_it_became_a_document(workspace: Path):
    result = _import(workspace, "price.csv", "品名,價格\n泵浦,100\n")

    assert result["kind"] == "document"
    assert "沒有「問題」「答案」兩欄" in result["notes"][0]


def test_every_unclear_row_is_listed_in_one_refusal(workspace: Path):
    _raw(workspace, "faq.csv", "q,a\nQ1,A1\nQ1,B1\nQ2,A2\nQ2,B2\n,孤兒答案\n")

    reason = commit_raw_documents("default")["skip_reasons"]["faq.csv"]

    assert "1 列只有答案、沒有題目（「孤兒答案」）" in reason
    assert "「Q1」、「Q2」在檔案裡有不同的答案" in reason


def test_the_written_labels_reach_the_search_index(workspace: Path):
    from knowledge.chunking import _extract_csv_chunks

    _languages()
    _import(workspace, "faq.csv", MIXED)

    chunks = _extract_csv_chunks(workspace / "knowledge" / "qa" / "faq.csv", workspace)
    languages = {chunk.metadata.get("language") for chunk in chunks}
    assert {"zh", "en", "es"} <= languages


# --- found in review ------------------------------------------------------------


def _workbook(path: Path, rows: list[list[str]]) -> None:
    import openpyxl

    book = openpyxl.Workbook()
    for row in rows:
        book.active.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)


def test_excel_imports_report_their_notes_too(workspace: Path):
    _workbook(workspace / "raw" / "faq.xlsx", [["問題", "答案", "備註"], ["Q1", "A1", "x"]])

    result = commit_raw_documents("default")["results"]["faq.xlsx"]

    assert "這些欄位沒有讀進去：備註" in result["notes"]


def test_a_second_question_or_answer_column_is_reported(workspace: Path):
    result = _import(workspace, "faq.csv", "問題,答案,Question,Answer\nQ1,A1,Q2,A2\n")

    assert "這些欄位沒有讀進去：Question、Answer" in result["notes"]


def test_a_split_table_keeps_new_questions_in_their_language_on_reupload(workspace: Path):
    _languages()
    _import(workspace, "faq.csv", MIXED)

    _import(workspace, "faq.csv", CHINESE + "有無障礙廁所嗎？,一樓電梯旁。\n")

    assert _questions_under("中文")["faq"] == {"營業時間是幾點？", "可以停車嗎？", "有無障礙廁所嗎？"}
    rows = (workspace / "knowledge" / "qa" / "faq.csv").read_text(encoding="utf-8").splitlines()
    assert next(row for row in rows if "有無障礙廁所嗎" in row).endswith(",zh")


def test_a_fully_labelled_table_from_before_this_change_reuploads_cleanly(workspace: Path, monkeypatch):
    import knowledge.qa_import_review as review

    table = 'q,a,language\r\n"多行\r\n題目？",答,zh\r\nHours,Nine,en\r\n'
    with monkeypatch.context() as before:
        # 這個改動之前匯入的表沒經過標語言，原樣存檔。
        before.setattr(review, "label_mixed_languages", lambda qa_csv, **_: qa_csv)
        _import(workspace, "faq.csv", table)

    result = _import(workspace, "faq.csv", table)

    assert result["added"] == 0


def test_mixing_languages_into_a_single_language_table_is_explained_not_claimed(workspace: Path):
    _languages()
    _import(workspace, "faq.csv", CHINESE)

    result = _import(workspace, "faq.csv", MIXED)

    assert "languages" not in result
    assert any("原本只有一種語言" in note for note in result["notes"])
    assert set(_questions_under("中文")["faq"]) >= {"What are the opening hours?"}


def test_no_split_is_claimed_without_language_categories(workspace: Path):
    result = _import(workspace, "faq.csv", MIXED)

    assert "languages" not in result


def test_a_refusal_lists_every_unclear_question(workspace: Path):
    rows = "".join(f"Q{n},A{n}\nQ{n},B{n}\n" for n in range(1, 6))
    _raw(workspace, "faq.csv", "q,a\n" + rows)

    reason = commit_raw_documents("default")["skip_reasons"]["faq.csv"]

    assert all(f"「Q{n}」" in reason for n in range(1, 6))


def test_no_split_is_claimed_when_every_row_names_its_own_category(workspace: Path):
    _languages()
    table = "問題,答案,分類\n營業時間是幾點？,早上九點。,服務\nWhat are the opening hours?,From nine.,服務\n"

    result = _import(workspace, "faq.csv", table)

    assert "languages" not in result


def test_a_repeated_column_name_in_one_excel_sheet_is_reported(workspace: Path):
    _workbook(workspace / "raw" / "faq.xlsx", [["問題", "答案", "問題", "答案"], ["Q1", "A1", "Q2", "A2"]])

    result = commit_raw_documents("default")["results"]["faq.xlsx"]

    assert "這些欄位沒有讀進去：問題、答案" in result["notes"]


def test_the_same_header_on_two_excel_sheets_is_not_a_repeat(workspace: Path):
    import openpyxl

    book = openpyxl.Workbook()
    book.active.append(["問題", "答案"])
    book.active.append(["Q1", "A1"])
    second = book.create_sheet("二")
    second.append(["問題", "答案"])
    second.append(["Q2", "A2"])
    (workspace / "raw").mkdir(parents=True, exist_ok=True)
    book.save(workspace / "raw" / "faq.xlsx")

    result = commit_raw_documents("default")["results"]["faq.xlsx"]

    assert "notes" not in result


def test_every_question_markdown_cannot_hold_is_listed(workspace: Path):
    table = (
        "q,a\n"
        '題一,"第一行\n## 小標題"\n'
        "題二,正常答案\n"
        '"題三\n換行",答案\n'
        '題四,"```\n程式碼沒有收尾"\n'
    )
    _raw(workspace, "faq.csv", table)

    reason = commit_raw_documents("default")["skip_reasons"]["faq.csv"]

    assert "「題一」" in reason and "「題三 換行」" in reason and "「題四」" in reason
    assert "題二" not in reason


# --- level1 / level2 columns and pre-write category validation ------------------


def _tree_paths_of_questions() -> dict[str, list[str]]:
    """Map each mounted question to its category label path from the root."""
    result: dict[str, list[str]] = {}

    def walk(node: dict, prefix: list[str]) -> None:
        here = [*prefix, node["label"]]
        for entry in node.get("qa_entries", []):
            result[entry["question"]] = here
        for child in node.get("children", []):
            walk(child, here)

    for root in qa_nodes.get_node_tree("default"):
        walk(root, [])
    return result


def test_level1_and_level2_place_chinese_table_under_language_category(workspace: Path):
    _languages()
    table = (
        "語言,第一層,第二層,問題,答案\n"
        "中文,服務,營業時間,服務中心的營業時間是幾點？,早上九點到下午六點。\n"
        "中文,購買,現場購買,可以現場購買商品嗎？,現場只展示樣品。\n"
    )

    result = _import(workspace, "faq.csv", table)

    assert _tree_paths_of_questions() == {
        "服務中心的營業時間是幾點？": ["中文", "服務", "營業時間"],
        "可以現場購買商品嗎？": ["中文", "購買", "現場購買"],
    }
    assert "notes" not in result


def test_excel_with_level1_and_level2_places_questions_without_ignored_notes(workspace: Path):
    _languages()
    _workbook(
        workspace / "raw" / "faq.xlsx",
        [
            ["語言", "第一層", "第二層", "問題", "答案"],
            ["中文", "服務", "營業時間", "幾點開門？", "早上九點。"],
        ],
    )

    summary = commit_raw_documents("default")
    result = summary["results"]["faq.xlsx"]

    assert _tree_paths_of_questions() == {"幾點開門？": ["中文", "服務", "營業時間"]}
    assert "notes" not in result


def test_mixed_language_table_with_levels_places_each_under_its_own_language(workspace: Path):
    _languages()
    table = (
        "語言,第一層,第二層,問題,答案\n"
        "中文,服務,營業時間,營業時間是幾點？,早上九點到下午六點。\n"
        "English,Service,Hours,What are the opening hours?,Nine to six.\n"
    )

    result = _import(workspace, "faq.csv", table)

    assert result["languages"] == {"zh": 1, "en": 1}
    assert _tree_paths_of_questions() == {
        "營業時間是幾點？": ["中文", "服務", "營業時間"],
        "What are the opening hours?": ["English", "Service", "Hours"],
    }


def test_level1_only_places_question_under_language_then_level1(workspace: Path):
    _languages()
    table = "語言,第一層,第二層,問題,答案\n中文,服務,,有停車位嗎？,後方有停車場。\n"

    _import(workspace, "faq.csv", table)

    assert _tree_paths_of_questions() == {"有停車位嗎？": ["中文", "服務"]}


def test_levels_without_language_categories_place_at_top_level(workspace: Path):
    table = (
        "第一層,第二層,問題,答案\n"
        "服務,營業時間,營業時間是幾點？,早上九點到下午六點。\n"
    )

    _import(workspace, "faq.csv", table)

    assert _tree_paths_of_questions() == {"營業時間是幾點？": ["服務", "營業時間"]}


def test_refuses_row_with_both_path_and_levels_without_writing(workspace: Path):
    _languages()
    nodes_file = workspace / "knowledge" / ".qa_nodes.json"
    nodes_before = nodes_file.read_bytes()
    table = (
        "分類,第一層,第二層,問題,答案\n"
        "中文/產品,服務,,題目一,答案一\n"
        "中文/產品,,保固,題目二,答案二\n"
        ",服務,營業時間,題目三,答案三\n"
    )
    _raw(workspace, "faq.csv", table)

    summary = commit_raw_documents("default")

    assert summary["committed"] == []
    assert summary["skipped"] == ["faq.csv"]
    reason = summary["skip_reasons"]["faq.csv"]
    assert "「題目一」、「題目二」同時填了「分類」和「第一層／第二層」，請只用一種" in reason
    assert "題目三" not in reason
    assert not (workspace / "knowledge" / "qa").exists()
    assert nodes_file.read_bytes() == nodes_before
    assert (workspace / "raw" / "faq.csv").exists()


def test_refuses_row_with_level2_without_level1_without_writing(workspace: Path):
    _languages()
    nodes_file = workspace / "knowledge" / ".qa_nodes.json"
    nodes_before = nodes_file.read_bytes()
    table = (
        "第一層,第二層,問題,答案\n"
        ",保養,題目一,答案一\n"
        ",保固,題目二,答案二\n"
        "產品,保養,題目三,答案三\n"
    )
    _raw(workspace, "faq.csv", table)

    summary = commit_raw_documents("default")

    assert summary["committed"] == []
    assert summary["skipped"] == ["faq.csv"]
    reason = summary["skip_reasons"]["faq.csv"]
    assert "「題目一」、「題目二」有第二層但沒有第一層" in reason
    assert "題目三" not in reason
    assert not (workspace / "knowledge" / "qa").exists()
    assert nodes_file.read_bytes() == nodes_before
    assert (workspace / "raw" / "faq.csv").exists()


def test_refuses_path_exceeding_two_levels_after_language_prefix_without_writing(workspace: Path):
    _languages()
    nodes_file = workspace / "knowledge" / ".qa_nodes.json"
    nodes_before = nodes_file.read_bytes()
    table = (
        "分類,問題,答案\n"
        "中文/A/B/C,題目一,答案一\n"
        "A/B/C,題目二,答案二\n"
        "中文/A/B,題目三,答案三\n"
    )
    _raw(workspace, "faq.csv", table)

    summary = commit_raw_documents("default")

    assert summary["committed"] == []
    assert summary["skipped"] == ["faq.csv"]
    reason = summary["skip_reasons"]["faq.csv"]
    assert "「題目一」、「題目二」的分類超過兩層" in reason
    assert "題目三" not in reason
    assert not (workspace / "knowledge" / "qa").exists()
    assert nodes_file.read_bytes() == nodes_before
    assert (workspace / "raw" / "faq.csv").exists()


def test_legacy_path_column_within_two_levels_still_works(workspace: Path):
    _languages()
    table = (
        "分類,問題,答案\n"
        "中文/產品/保養,如何保養？,保持乾燥。\n"
        "服務/停車,有停車位嗎？,後方有停車場。\n"
    )

    _import(workspace, "faq.csv", table)

    assert _tree_paths_of_questions() == {
        "如何保養？": ["中文", "產品", "保養"],
        "有停車位嗎？": ["服務", "停車"],
    }


def test_import_mounts_questions_in_index_order_across_categories(workspace: Path):
    _languages()
    table = (
        "順序,第一層,問題,答案\n"
        "3,產品,產品第三題,答案三\n"
        "1,產品,產品第一題,答案一\n"
        "2,產品,產品第二題,答案二\n"
        "3,服務,服務第三題,答案三\n"
        "1,服務,服務第一題,答案一\n"
        "2,服務,服務第二題,答案二\n"
    )

    _import(workspace, "ordered.csv", table)

    nodes = qa_nodes.list_nodes("default")
    by_label = {node["label"]: node for node in nodes.values()}
    assert [e["question"] for e in by_label["產品"]["qa_entries"]] == [
        "產品第一題",
        "產品第二題",
        "產品第三題",
    ]
    assert [e["question"] for e in by_label["服務"]["qa_entries"]] == [
        "服務第一題",
        "服務第二題",
        "服務第三題",
    ]


def test_reupload_keeps_mounted_order_and_appends_new_questions_in_index_order(workspace: Path):
    _languages()
    first = (
        "順序,第一層,問題,答案\n"
        "2,產品,既有二,A2\n"
        "1,產品,既有一,A1\n"
        "1,服務,服務題,B1\n"
    )
    _import(workspace, "ordered.csv", first)

    # 模擬工作人員把「產品」裡的既有順序調成 [既有二, 既有一]。
    nodes = qa_nodes.list_nodes("default")
    product_id = next(nid for nid, node in nodes.items() if node["label"] == "產品")
    entries = list(nodes[product_id]["qa_entries"])
    qa_nodes.update_node(product_id, {"qa_entries": list(reversed(entries))})

    second = (
        "順序,第一層,問題,答案\n"
        "1,產品,既有一,A1\n"
        "2,產品,既有二,A2\n"
        "4,產品,新增四,A4\n"
        "3,產品,新增三,A3\n"
        "1,服務,服務題,B1\n"
    )
    _import(workspace, "ordered.csv", second)

    after = qa_nodes.get_node(product_id)["qa_entries"]
    assert [e["question"] for e in after] == ["既有二", "既有一", "新增三", "新增四"]

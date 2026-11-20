"""Quick Q&A Excel export: layout, round-trip import, and vendor visibility."""

from __future__ import annotations

from datetime import UTC, datetime
import io
import json
import sys
from pathlib import Path
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo

import openpyxl
import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import knowledge.normalizer
import knowledge.workspace
from config import get_settings
from knowledge import qa_nodes
from knowledge.doc_meta import upsert_document_meta
from knowledge.qa_csv import qa_markdown_block
from knowledge.qa_export import EXPORT_COLUMNS, EXPORT_SHEET_TITLE, XLSX_MEDIA_TYPE, export_filename
from knowledge.qa_merged import _rows_of
from knowledge.raw_import import commit_raw_documents
from main import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import routes.knowledge_qa

    monkeypatch.setattr(routes.knowledge_qa, "schedule_reindex", lambda project_id="default": None)
    monkeypatch.setattr(knowledge.normalizer, "normalize_to_markdown", lambda text: text)
    return TestClient(
        app,
        headers={"X-Internal-Token": get_settings().gateway_internal_token},
    )


def _write_qa_md(
    project_id: str,
    relative: str,
    entries: list[tuple[str, str, str, str, bool]],
    *,
    language: str = "zh",
) -> str:
    root = knowledge.workspace.ensure_workspace_scaffold(project_id)
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n\n".join(
        qa_markdown_block(q, a, img=img, url=url, hidden=hidden)
        for q, a, img, url, hidden in entries
    )
    path.write_text(content + "\n", encoding="utf-8")
    upsert_document_meta(relative, project_id, source_type="qa", language=language)
    return relative


def _mount(project_id: str, node_id: str, source: str, question: str) -> None:
    qa_nodes.add_qa_entry_to_node(
        node_id,
        {"question": question, "source_path": source},
        project_id=project_id,
    )


def _read_workbook(payload: bytes) -> tuple[str, list[tuple]]:
    book = openpyxl.load_workbook(io.BytesIO(payload), data_only=True)
    try:
        assert len(book.worksheets) == 1
        sheet = book.worksheets[0]
        return sheet.title, list(sheet.iter_rows(values_only=True))
    finally:
        book.close()


def _decode_attachment_filename(header_value: str) -> str:
    prefix = "attachment; filename*=UTF-8''"
    assert header_value.startswith(prefix), header_value
    return unquote(header_value[len(prefix):])


def _seed_standard_project(project_id: str) -> None:
    """Populate the scenario from the brief:
    - 中文 › 服務 › 營業時間: 2 dedicated questions + 1 shared question
    - 中文 › 產品: 1 hidden question + the same shared question
    - Uncategorized: 1 question not mounted on any node
    """
    source = _write_qa_md(
        project_id,
        "knowledge/qa/faq.md",
        [
            (
                "營業時間是幾點？",
                "週一到週五早上九點到下午六點。",
                "hours.png",
                "https://example.com/hours",
                False,
            ),
            ("假日有營業嗎？", "週六十點到五點，週日公休。", "", "", False),
            (
                "如何聯絡客服？",
                "請撥打 0800-000-000。",
                "",
                "https://example.com/contact",
                False,
            ),
            ("內部測試產品規格？", "測試中，尚未公開。", "", "", True),
            ("尚未分類的題目？", "這題目前不在選單上。", "", "", False),
        ],
    )
    qa_nodes.create_node("zh", "中文", project_id=project_id)
    qa_nodes.create_node("svc", "服務", parent_ids=["zh"], project_id=project_id)
    qa_nodes.create_node("hours", "營業時間", parent_ids=["svc"], project_id=project_id)
    qa_nodes.create_node("prod", "產品", parent_ids=["zh"], project_id=project_id)

    _mount(project_id, "hours", source, "營業時間是幾點？")
    _mount(project_id, "hours", source, "假日有營業嗎？")
    _mount(project_id, "hours", source, "如何聯絡客服？")
    _mount(project_id, "prod", source, "內部測試產品規格？")
    _mount(project_id, "prod", source, "如何聯絡客服？")


def test_export_workbook_columns_order_display_shared_uncategorized_and_filename(
    client: TestClient,
) -> None:
    project_id = "export-src"
    _seed_standard_project(project_id)

    response = client.get("/brain/knowledge/qa/export", params={"project_id": project_id})

    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX_MEDIA_TYPE
    expected_date = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d")
    expected_name = f"快速回覆_{expected_date}.xlsx"
    assert response.headers["content-disposition"] == (
        f"attachment; filename*=UTF-8''{quote(expected_name, safe='')}"
    )

    sheet_title, rows = _read_workbook(response.content)
    assert sheet_title == EXPORT_SHEET_TITLE
    assert rows == [
        EXPORT_COLUMNS,
        (
            "中文",
            "服務",
            "營業時間",
            "營業時間是幾點？",
            "週一到週五早上九點到下午六點。",
            "hours.png",
            "https://example.com/hours",
            "是",
            1,
        ),
        (
            "中文",
            "服務",
            "營業時間",
            "假日有營業嗎？",
            "週六十點到五點，週日公休。",
            None,
            None,
            "是",
            2,
        ),
        (
            "中文",
            "服務",
            "營業時間",
            "如何聯絡客服？",
            "請撥打 0800-000-000。",
            None,
            "https://example.com/contact",
            "是",
            3,
        ),
        (
            "中文",
            "產品",
            None,
            "內部測試產品規格？",
            "測試中，尚未公開。",
            None,
            None,
            "否",
            1,
        ),
        (
            "中文",
            "產品",
            None,
            "如何聯絡客服？",
            "請撥打 0800-000-000。",
            None,
            "https://example.com/contact",
            "是",
            2,
        ),
        (
            None,
            None,
            None,
            "尚未分類的題目？",
            "這題目前不在選單上。",
            None,
            None,
            "是",
            None,
        ),
    ]


def _tree_rows_by_path(project_id: str) -> dict[tuple[str, ...], list[tuple[str, str, str, str, bool]]]:
    result: dict[tuple[str, ...], list[tuple[str, str, str, str, bool]]] = {}

    def walk(node: dict, prefix: tuple[str, ...]) -> None:
        here = (*prefix, node["label"])
        node_rows = _rows_of(node, project_id)
        if node_rows:
            result[here] = [
                (r["q"], r["a"], r["img"], r["url"], bool(r["hidden"]))
                for r in node_rows
            ]
        for child in node.get("children", []):
            walk(child, here)

    for root in qa_nodes.get_node_tree(project_id):
        walk(root, ())
    return result


def test_roundtrip_export_and_reimport_into_empty_chinese_project(
    client: TestClient,
) -> None:
    src_project = "roundtrip-src"
    dst_project = "roundtrip-dst"
    _seed_standard_project(src_project)

    response = client.get("/brain/knowledge/qa/export", params={"project_id": src_project})
    assert response.status_code == 200
    filename = _decode_attachment_filename(response.headers["content-disposition"])
    stem = Path(filename).stem

    dst_root = knowledge.workspace.ensure_workspace_scaffold(dst_project)
    qa_nodes.create_node("zh", "中文", project_id=dst_project)
    raw_file = dst_root / "raw" / filename
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_bytes(response.content)

    summary = commit_raw_documents(dst_project, normalize=False)
    assert filename in summary["results"], summary["skip_reasons"]
    result = summary["results"][filename]
    # 9 個匯出欄位都在匯入已知欄名內，不會產生「這些欄位沒有讀進去」的提示。
    assert not any("沒有讀進去" in note for note in result.get("notes", []))

    actual = _tree_rows_by_path(dst_project)
    # 註：現有匯入管線（qa_csv.qa_csv_row_extras、qa_import_review.question_paths、
    # qa_nodes.place_questions_by_path，均屬本次不准動檔案）以題目文字為鍵、每題只保留最後一筆
    # 分類路徑且只掛載一次；因此同時掛在兩個分類的「如何聯絡客服？」匯出時會有兩列，
    # 但重傳進空專案時只會掛回在排序後最後出現的那一個分類（這裡為「中文 › 服務 › 營業時間」），
    # 不會同時掛進「中文 › 產品」。
    assert actual == {
        ("中文", "服務", "營業時間"): [
            (
                "營業時間是幾點？",
                "週一到週五早上九點到下午六點。",
                "hours.png",
                "https://example.com/hours",
                False,
            ),
            ("假日有營業嗎？", "週六十點到五點，週日公休。", "", "", False),
            (
                "如何聯絡客服？",
                "請撥打 0800-000-000。",
                "",
                "https://example.com/contact",
                False,
            ),
        ],
        ("中文", "產品"): [
            ("內部測試產品規格？", "測試中，尚未公開。", "", "", True),
        ],
        ("中文", stem): [
            ("尚未分類的題目？", "這題目前不在選單上。", "", "", False),
        ],
    }


def test_vendor_export_hides_hidden_sources_but_keeps_visible_and_menu_only(
    client: TestClient,
) -> None:
    project_id = "vendor-export"
    hidden_source = _write_qa_md(
        project_id,
        "knowledge/.hidden/secret.md",
        [
            ("內部限定題？", "只有內部看得到。", "", "", False),
            ("內部未分類題？", "也不該出現在廠商匯出。", "", "", False),
        ],
    )
    public_source = _write_qa_md(
        project_id,
        "knowledge/qa/public.md",
        [
            ("公開題？", "大家都能看。", "", "", False),
            ("公開未分類題？", "公開但未分類。", "", "", False),
        ],
    )
    qa_nodes.create_node("zh", "中文", project_id=project_id)
    qa_nodes.create_node("svc", "服務", parent_ids=["zh"], project_id=project_id)
    _mount(project_id, "svc", hidden_source, "內部限定題？")
    _mount(project_id, "svc", public_source, "公開題？")
    qa_nodes.add_qa_entry_to_node(
        "svc",
        {"question": "選單專用題？", "source_path": ""},
        project_id=project_id,
    )

    vendor_resp = client.get(
        "/brain/knowledge/qa/export",
        params={"project_id": project_id},
        headers={"X-OpenVMan-Vendor": "1"},
    )
    assert vendor_resp.status_code == 200
    _, vendor_rows = _read_workbook(vendor_resp.content)
    assert vendor_rows == [
        EXPORT_COLUMNS,
        ("中文", "服務", None, "公開題？", "大家都能看。", None, None, "是", 1),
        ("中文", "服務", None, "選單專用題？", None, None, None, "是", 2),
        (None, None, None, "公開未分類題？", "公開但未分類。", None, None, "是", None),
    ]

    internal_resp = client.get(
        "/brain/knowledge/qa/export",
        params={"project_id": project_id},
    )
    assert internal_resp.status_code == 200
    _, internal_rows = _read_workbook(internal_resp.content)
    assert internal_rows == [
        EXPORT_COLUMNS,
        ("中文", "服務", None, "內部限定題？", "只有內部看得到。", None, None, "是", 1),
        ("中文", "服務", None, "公開題？", "大家都能看。", None, None, "是", 2),
        ("中文", "服務", None, "選單專用題？", None, None, None, "是", 3),
        (None, None, None, "內部未分類題？", "也不該出現在廠商匯出。", None, None, "是", None),
        (None, None, None, "公開未分類題？", "公開但未分類。", None, None, "是", None),
    ]


def test_export_flattens_legacy_categories_deeper_than_two_levels(
    client: TestClient,
) -> None:
    project_id = "deep-legacy"
    source = _write_qa_md(
        project_id,
        "knowledge/qa/deep.md",
        [("怎麼掛號？", "網路或現場皆可。", "", "", False)],
    )
    root = knowledge.workspace.ensure_workspace_scaffold(project_id)
    nodes_file = root / "knowledge" / ".qa_nodes.json"
    nodes_file.parent.mkdir(parents=True, exist_ok=True)
    # 舊資料可能超過兩層，直接寫入 .qa_nodes.json 模擬。
    nodes_file.write_text(
        json.dumps(
            {
                "nodes": {
                    "zh": {
                        "label": "中文",
                        "parent_ids": [],
                        "child_ids": ["svc"],
                        "order": 1.0,
                        "hidden": False,
                        "qa_entries": [],
                    },
                    "svc": {
                        "label": "服務",
                        "parent_ids": ["zh"],
                        "child_ids": ["clinic"],
                        "order": 1.0,
                        "hidden": False,
                        "qa_entries": [],
                    },
                    "clinic": {
                        "label": "門診",
                        "parent_ids": ["svc"],
                        "child_ids": ["reg"],
                        "order": 1.0,
                        "hidden": False,
                        "qa_entries": [],
                    },
                    "reg": {
                        "label": "掛號",
                        "parent_ids": ["clinic"],
                        "child_ids": [],
                        "order": 1.0,
                        "hidden": False,
                        "qa_entries": [
                            {
                                "question": "怎麼掛號？",
                                "source_path": source,
                                "hidden": False,
                                "image_id": None,
                            }
                        ],
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/brain/knowledge/qa/export", params={"project_id": project_id})
    assert response.status_code == 200
    _, rows = _read_workbook(response.content)
    assert rows == [
        EXPORT_COLUMNS,
        ("中文", "服務", "門診 / 掛號", "怎麼掛號？", "網路或現場皆可。", None, None, "是", 1),
    ]


def test_export_non_language_root_leaves_language_column_blank(client: TestClient) -> None:
    project_id = "no-lang-root"
    source = _write_qa_md(
        project_id,
        "knowledge/qa/general.md",
        [("可以退貨嗎？", "七天內可辦理退貨。", "", "", False)],
    )
    qa_nodes.create_node("faq", "常見問題", project_id=project_id)
    qa_nodes.create_node("returns", "退換貨", parent_ids=["faq"], project_id=project_id)
    _mount(project_id, "returns", source, "可以退貨嗎？")

    response = client.get("/brain/knowledge/qa/export", params={"project_id": project_id})
    assert response.status_code == 200
    _, rows = _read_workbook(response.content)
    assert rows == [
        EXPORT_COLUMNS,
        (None, "常見問題", "退換貨", "可以退貨嗎？", "七天內可辦理退貨。", None, None, "是", 1),
    ]


def test_export_filename_uses_taipei_date() -> None:
    # UTC 2026-11-20 17:30 對應台北時間 2026-11-21 01:30。
    utc_time = datetime(2026, 11, 20, 17, 30, tzinfo=UTC)
    assert export_filename(utc_time) == "快速回覆_20261121.xlsx"


def test_export_empty_project_returns_header_only_workbook(client: TestClient) -> None:
    response = client.get("/brain/knowledge/qa/export", params={"project_id": "empty-export"})
    assert response.status_code == 200
    title, rows = _read_workbook(response.content)
    assert title == EXPORT_SHEET_TITLE
    assert rows == [EXPORT_COLUMNS]


def test_export_preserves_leading_equals_as_literal_text(client: TestClient) -> None:
    project_id = "equals-text"
    source = _write_qa_md(
        project_id,
        "knowledge/qa/formula.md",
        [("=SUM(A1:A2) 是什麼？", "=1+1 範例文字", "", "", False)],
    )
    qa_nodes.create_node("zh", "中文", project_id=project_id)
    qa_nodes.create_node("svc", "服務", parent_ids=["zh"], project_id=project_id)
    _mount(project_id, "svc", source, "=SUM(A1:A2) 是什麼？")

    response = client.get("/brain/knowledge/qa/export", params={"project_id": project_id})
    assert response.status_code == 200
    _, rows = _read_workbook(response.content)
    assert rows[1][3] == "=SUM(A1:A2) 是什麼？"
    assert rows[1][4] == "=1+1 範例文字"


def test_export_strips_control_characters_excel_cannot_store(client: TestClient) -> None:
    """Answers pasted from Word can carry \\x0b; one such answer must not break the whole export."""
    project_id = "export-control-chars"
    source = _write_qa_md(project_id, "knowledge/qa/word.md", [("營業時間？", "上午\x0b下午", "", "", False)])
    qa_nodes.create_node("hours", "營業時間", project_id=project_id)
    _mount(project_id, "hours", source, "營業時間？")

    response = client.get("/brain/knowledge/qa/export", params={"project_id": project_id})

    assert response.status_code == 200, response.text
    _title, rows = _read_workbook(response.content)
    assert any(row[4] == "上午下午" for row in rows)

"""Tests for knowledge.converters file → plain-text extraction."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

converters = importlib.import_module("knowledge.converters")


def test_csv_emits_col_value_lines(tmp_path: Path):
    csv_path = tmp_path / "hours.csv"
    csv_path.write_text(
        "星期,上午,下午\n週一,09:00-12:00,14:00-18:00\n週二,休診,14:00-18:00\n",
        encoding="utf-8",
    )

    result = converters.convert_to_text(csv_path)

    assert result is not None
    lines = result.splitlines()
    assert lines[0] == "星期: 週一 ｜ 上午: 09:00-12:00 ｜ 下午: 14:00-18:00"
    assert lines[1] == "星期: 週二 ｜ 上午: 休診 ｜ 下午: 14:00-18:00"


def test_qa_csv_emits_heading_per_row(tmp_path: Path):
    """A Q&A CSV becomes one ## heading per question, so each row can form its
    own graph sub-node instead of collapsing into a single file-level topic."""
    csv_path = tmp_path / "faq.csv"
    csv_path.write_text(
        "index,q,a,img\n"
        "001,什麼是五十肩？,肩關節囊發炎沾黏。,\n"
        "002,為什麼叫五十肩？,好發於中年。,\n",
        encoding="utf-8",
    )

    result = converters.convert_to_text(csv_path)

    assert result is not None
    assert "## 什麼是五十肩？" in result
    assert "肩關節囊發炎沾黏。" in result
    assert "## 為什麼叫五十肩？" in result
    # The two FAQs must be separated into distinct heading blocks.
    assert result.index("## 什麼是五十肩？") < result.index("## 為什麼叫五十肩？")


def test_qa_csv_with_chinese_headers(tmp_path: Path):
    """Q&A detection also handles 問題/回答 column names."""
    csv_path = tmp_path / "faq2.csv"
    csv_path.write_text(
        "問題,回答,圖片 (Image),連結 (URL)\n"
        "什麼是五十肩？,肩關節囊發炎。,,\n",
        encoding="utf-8",
    )

    result = converters.convert_to_text(csv_path)

    assert result is not None
    assert "## 什麼是五十肩？" in result
    assert "肩關節囊發炎。" in result


def test_txt_passthrough(tmp_path: Path):
    txt_path = tmp_path / "note.txt"
    content = "第一行\n第二行\n"
    txt_path.write_text(content, encoding="utf-8")

    assert converters.convert_to_text(txt_path) == content


def test_md_passthrough(tmp_path: Path):
    md_path = tmp_path / "doc.md"
    content = "# 標題\n\n內容段落。\n"
    md_path.write_text(content, encoding="utf-8")

    assert converters.convert_to_text(md_path) == content


def test_xlsx_round_trip(tmp_path: Path):
    import openpyxl

    xlsx_path = tmp_path / "book.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "門診"
    sheet.append(["科別", "醫師"])
    sheet.append(["內科", "王醫師"])
    sheet.append(["外科", "李醫師"])
    workbook.save(xlsx_path)

    result = converters.convert_to_text(xlsx_path)

    assert result is not None
    assert "# 門診" in result
    assert "科別: 內科 ｜ 醫師: 王醫師" in result
    assert "科別: 外科 ｜ 醫師: 李醫師" in result


def test_qa_xlsx_emits_heading_per_row(tmp_path: Path):
    import openpyxl

    xlsx_path = tmp_path / "faq.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "FAQ"
    sheet.append(["index", "question", "answer"])
    sheet.append(["001", "如何上傳題庫？", "到上傳分頁選 CSV 或 XLSX。"])
    sheet.append(["002", "可以手動新增嗎？", "可以，到手動分頁新增 QA。"])
    workbook.save(xlsx_path)

    result = converters.convert_to_text(xlsx_path)

    assert result is not None
    assert "# FAQ" in result
    assert "## 如何上傳題庫？" in result
    assert "到上傳分頁選 CSV 或 XLSX。" in result
    assert "## 可以手動新增嗎？" in result
    assert result.index("## 如何上傳題庫？") < result.index("## 可以手動新增嗎？")


def test_docx_round_trip(tmp_path: Path):
    import docx

    docx_path = tmp_path / "doc.docx"
    document = docx.Document()
    document.add_paragraph("這是第一段。")
    document.add_paragraph("這是第二段。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "姓名"
    table.cell(0, 1).text = "電話"
    table.cell(1, 0).text = "張三"
    table.cell(1, 1).text = "0912345678"
    document.save(docx_path)

    result = converters.convert_to_text(docx_path)

    assert result is not None
    assert "這是第一段。" in result
    assert "這是第二段。" in result
    assert "姓名" in result
    assert "張三" in result
    assert "0912345678" in result


def test_unsupported_suffix_returns_none(tmp_path: Path):
    zip_path = tmp_path / "archive.zip"
    zip_path.write_bytes(b"PK\x03\x04not-a-real-zip")

    assert converters.convert_to_text(zip_path) is None


def test_corrupt_docx_returns_none(tmp_path: Path):
    bad_path = tmp_path / "broken.docx"
    bad_path.write_bytes(b"this is not a valid docx file at all")

    assert converters.convert_to_text(bad_path) is None


def test_empty_text_returns_none(tmp_path: Path):
    empty_path = tmp_path / "empty.txt"
    empty_path.write_text("   \n\t\n", encoding="utf-8")

    assert converters.convert_to_text(empty_path) is None


def test_supported_suffixes_set():
    assert converters.SUPPORTED_SUFFIXES == frozenset(
        {".md", ".txt", ".csv", ".docx", ".xlsx", ".pdf"}
    )


def test_qa_csv_conversion_metadata(tmp_path: Path):
    csv_path = tmp_path / "metadata_faq.csv"
    csv_path.write_text(
        "q,a,img,url\n"
        "How to use?,Run the tool.,img_url.png,https://example.com\n",
        encoding="utf-8"
    )

    result = converters.convert_to_text(csv_path)
    assert result is not None
    assert "## How to use?" in result
    assert "Run the tool." in result
    assert '<!-- qa_metadata: {"img": "img_url.png", "url": "https://example.com"} -->' in result


def _workbook(path: Path, sheets: dict[str, list[list[object]]]) -> Path:
    import openpyxl

    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    workbook.save(path)
    return path


def _qa_rows(path: Path) -> list[dict[str, object]]:
    from knowledge.qa_csv import parse_qa_csv

    csv_bytes = converters.qa_table_csv_bytes(path, path.read_bytes())
    assert csv_bytes is not None
    return parse_qa_csv(csv_bytes)


def test_qa_workbook_keeps_image_link_and_display_columns(tmp_path: Path):
    path = _workbook(tmp_path / "faq.xlsx", {
        "FAQ": [
            ["題目", "回答", "圖片", "連結", "顯示", "備註"],
            ["Q1", "A1", "p.png", "https://example.com", False, "內部備註"],
            ["Q2", "A2", None, None, None, None],
        ],
    })

    assert _qa_rows(path) == [
        {"q": "Q1", "a": "A1", "img": "p.png", "url": "https://example.com", "hidden": True},
        {"q": "Q2", "a": "A2", "img": "", "url": "", "hidden": False},
    ]


def test_qa_workbook_joins_sheets_in_order_without_mixing_their_indexes(tmp_path: Path):
    path = _workbook(tmp_path / "faq.xlsx", {
        "第一張": [["index", "q", "a"], [2, "一之二", "A"], [1, "一之一", "A"]],
        "第二張": [["index", "q", "a"], [1, "二之一", "A"], [2, "二之二", "A"]],
    })

    assert [row["q"] for row in _qa_rows(path)] == ["一之一", "一之二", "二之一", "二之二"]


def test_qa_workbook_ignores_empty_sheets_and_blank_rows(tmp_path: Path):
    path = _workbook(tmp_path / "faq.xlsx", {
        "空的": [],
        "只有空白": [[None, "  "]],
        "FAQ": [[None, None], ["q", "a"], [None, None], ["Q1", 100]],
    })

    assert [(row["q"], row["a"]) for row in _qa_rows(path)] == [("Q1", "100")]


def test_workbook_with_one_other_sheet_is_not_a_qa_table(tmp_path: Path):
    path = _workbook(tmp_path / "book.xlsx", {
        "FAQ": [["q", "a"], ["Q1", "A1"]],
        "價目表": [["品項", "價格"], ["A", 100]],
    })

    assert converters.qa_table_csv_bytes(path, path.read_bytes()) is None


def test_workbook_without_any_content_is_not_a_qa_table(tmp_path: Path):
    path = _workbook(tmp_path / "book.xlsx", {"空的": []})

    assert converters.qa_table_csv_bytes(path, path.read_bytes()) is None


def test_corrupt_workbook_is_not_a_qa_table(tmp_path: Path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"this is not a workbook")

    assert converters.qa_table_csv_bytes(path, path.read_bytes()) is None


def test_qa_table_csv_bytes_for_csv_files(tmp_path: Path):
    qa = tmp_path / "faq.csv"
    qa.write_bytes("問題,答案\nQ1,A1\n".encode("utf-8"))
    table = tmp_path / "table.csv"
    table.write_bytes(b"name,age\nAlice,20\n")
    text = tmp_path / "note.txt"
    text.write_bytes("問題,答案\n".encode("utf-8"))

    assert converters.qa_table_csv_bytes(qa, qa.read_bytes()) == qa.read_bytes()
    assert converters.qa_table_csv_bytes(table, table.read_bytes()) is None
    assert converters.qa_table_csv_bytes(text, text.read_bytes()) is None

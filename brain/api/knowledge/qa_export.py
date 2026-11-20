"""Export a project's quick Q&A tree and uncategorized questions as an Excel workbook.

匯出的 Excel（.xlsx）與問答表匯入格式相同，工作人員可以直接修改後再上傳。
一列一題一個位置：同一題掛在多個分類時每個位置各輸出一列，未分類的題目排在最後。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import io
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import openpyxl
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from knowledge.qa_merged import _rows_of
from knowledge.qa_nodes import get_node_tree, is_language_label
from knowledge.qa_questions import list_all_questions

EXPORT_SHEET_TITLE = "快速回覆"
EXPORT_COLUMNS: tuple[str, ...] = (
    "語言",
    "第一層",
    "第二層",
    "問題",
    "答案",
    "圖片",
    "連結",
    "顯示",
    "順序",
)
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_TAIPEI_TZ = ZoneInfo("Asia/Taipei")
_DISPLAY_SHOW = "是"
_DISPLAY_HIDE = "否"


def export_filename(now: datetime | None = None) -> str:
    """Filename for the downloaded workbook, dated in Asia/Taipei."""
    current = now.astimezone(_TAIPEI_TZ) if now is not None else datetime.now(_TAIPEI_TZ)
    return f"{EXPORT_SHEET_TITLE}_{current.strftime('%Y%m%d')}.xlsx"


def content_disposition_attachment(filename: str) -> str:
    """RFC 5987 attachment header with percent-encoded UTF-8 filename."""
    return f"attachment; filename*=UTF-8''{quote(filename, safe='')}"


def _split_category_path(path: list[str]) -> tuple[str, str, str]:
    """Map a root-to-node label path into ``(語言, 第一層, 第二層)``.

    分類樹最多兩層（語言分類不計）；若遇到更深的舊資料，第二層以下以「 / 」接起來放第二層。
    """
    if not path:
        return "", "", ""
    if is_language_label(path[0]):
        language, rest = path[0], path[1:]
    else:
        language, rest = "", path
    level1 = rest[0] if rest else ""
    level2 = " / ".join(rest[1:]) if len(rest) > 1 else ""
    return language, level1, level2


def _filter_node_entries(
    node: dict[str, Any],
    visible: Callable[[str], bool] | None,
) -> dict[str, Any]:
    if visible is None:
        return node
    return {
        **node,
        "qa_entries": [
            entry
            for entry in node.get("qa_entries", [])
            if not (source := entry.get("source_path")) or visible(source)
        ],
    }


def _display_label(hidden: bool) -> str:
    return _DISPLAY_HIDE if hidden else _DISPLAY_SHOW


def collect_export_rows(
    project_id: str = "default",
    *,
    visible: Callable[[str], bool] | None = None,
) -> list[tuple[str, str, str, str, str, str, str, str, int | str]]:
    """Collect every quick Q&A row in tree order, followed by uncategorized questions."""
    rows: list[tuple[str, str, str, str, str, str, str, str, int | str]] = []

    def walk(node: dict[str, Any], prefix: list[str]) -> None:
        label = node.get("label") or node["node_id"]
        path = [*prefix, label]
        language, level1, level2 = _split_category_path(path)
        node_rows = _rows_of(_filter_node_entries(node, visible), project_id)
        for position, row in enumerate(node_rows, start=1):
            rows.append((
                language,
                level1,
                level2,
                row.get("q") or "",
                row.get("a") or "",
                row.get("img") or "",
                row.get("url") or "",
                _display_label(bool(row.get("hidden", False))),
                position,
            ))
        for child in node.get("children", []):
            walk(child, path)

    for root in get_node_tree(project_id):
        walk(root, [])

    all_questions = list_all_questions(project_id, visible=visible)["questions"]
    for item in all_questions:
        if item.get("category_ids"):
            continue
        rows.append((
            "",
            "",
            "",
            item.get("question") or "",
            item.get("answer") or "",
            item.get("image") or "",
            item.get("url") or "",
            _display_label(bool(item.get("hidden_in_file", False))),
            "",
        ))
    return rows


def build_qa_export_workbook(
    project_id: str = "default",
    *,
    visible: Callable[[str], bool] | None = None,
) -> bytes:
    """Serialize the project's quick Q&A questions into an ``.xlsx`` byte payload."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = EXPORT_SHEET_TITLE
    sheet.append(list(EXPORT_COLUMNS))

    for row_index, values in enumerate(collect_export_rows(project_id, visible=visible), start=2):
        for col_index, value in enumerate(values, start=1):
            if isinstance(value, str):
                # 從 Word 複製來的答案常帶 \x0b 之類的控制字元，Excel 存不下，整份匯出會失敗。
                value = ILLEGAL_CHARACTERS_RE.sub("", value)
            cell = sheet.cell(
                row=row_index,
                column=col_index,
                value=value if value != "" else None,
            )
            if isinstance(value, str) and value.startswith("="):
                cell.data_type = "s"

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()

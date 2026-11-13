"""Extract readable plain text from arbitrary uploaded files.

This module performs *format → text* extraction only. It does NOT produce
final markdown — a separate LLM normalizer cleans the raw text afterwards.

Each format has a small private helper (``_convert_*``). The public entry
point :func:`convert_to_text` dispatches on suffix and never raises: any
extraction failure (unsupported format, corrupt file, empty result) yields
``None`` so the caller can leave such files untouched.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Sequence
from pathlib import Path

from knowledge.qa_csv import (
    _rows_to_csv_bytes,
    _sort_by_index,
    convert_csv_to_qa_markdown,
    is_qa_csv,
    normalize_fieldname,
    parse_csv_table,
)

logger = logging.getLogger("brain.knowledge.converters")

# Joins column:value pairs within a single row (full-width separators read
# better for the predominantly Chinese-language knowledge base).
_PAIR_SEP = " ｜ "
_KV_SEP = ": "
# 問答表帶進問答文件的欄位，順序就是輸出 CSV 的欄位順序；其他欄位（備註等）不帶。
_QA_TABLE_FIELDS = ("q", "a", "img", "url", "display", "language", "path")


def _cell_text(row: Sequence[object], index: int) -> str:
    if index >= len(row):
        return ""
    value = row[index]
    return "" if value is None else str(value).strip()


def _row_to_line(header: list[str], row: Sequence[object]) -> str:
    """Render one table row as ``col: val ｜ col: val`` using header names.

    Cell values may be non-strings (xlsx yields int/float/None), so each value
    is coerced via ``str`` before trimming.
    """
    pairs: list[str] = []
    for index, value in enumerate(row):
        cell = "" if value is None else str(value).strip()
        if cell == "":
            continue
        column = header[index] if index < len(header) else f"col{index + 1}"
        pairs.append(f"{column}{_KV_SEP}{cell}")
    return _PAIR_SEP.join(pairs)


def _convert_text(path: Path) -> str:
    """Read a plain-text / markdown file verbatim."""
    return path.read_text(encoding="utf-8-sig")


def _qa_column_indices(header: list[str]) -> tuple[int, int] | None:
    """Return (question_index, answer_index) if the header is a FAQ table."""
    q_index = a_index = None
    for index, name in enumerate(header):
        canonical = normalize_fieldname(name)
        if q_index is None and canonical == "q":
            q_index = index
        elif a_index is None and canonical == "a":
            a_index = index
    if q_index is None or a_index is None:
        return None
    return q_index, a_index


def _convert_qa_rows(
    rows: Sequence[Sequence[object]],
    q_index: int,
    a_index: int,
) -> str:
    """Render FAQ table rows as ``## question`` heading blocks."""
    blocks: list[str] = []
    for row in rows:
        question = _cell_text(row, q_index)
        answer = _cell_text(row, a_index)
        if not question and not answer:
            continue
        heading = question or "未命名問題"
        blocks.append(f"## {heading}\n\n{answer}" if answer else f"## {heading}")
    return "\n\n".join(blocks)


def _convert_csv(path: Path) -> str:
    """Render a CSV as text.

    FAQ tables (question + answer columns) become ``## question`` heading blocks
    so each row is a distinct, individually-retrievable section. Other tables
    fall back to one ``col: val ｜ ...`` line per row.
    """
    try:
        file_bytes = path.read_bytes()
    except Exception:
        return ""
    if is_qa_csv(file_bytes):
        return convert_csv_to_qa_markdown(file_bytes)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    if not rows:
        return ""
    header = [str(cell).strip() for cell in rows[0]]
    lines = [_row_to_line(header, row) for row in rows[1:]]
    return "\n".join(line for line in lines if line)


def _convert_docx(path: Path) -> str:
    """Extract paragraph text and table cell text from a .docx document."""
    import docx

    document = docx.Document(str(path))
    parts: list[str] = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            parts.append(text)

    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            line = _PAIR_SEP.join(cell for cell in cells if cell)
            if line:
                parts.append(line)

    return "\n".join(parts)


def _convert_xlsx(path: Path) -> str:
    """Render each worksheet as ``# title`` plus ``col: val ｜ ...`` rows."""
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sections: list[str] = []
    try:
        for sheet in workbook.worksheets:
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                continue
            header = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
            qa_indices = _qa_column_indices(header)
            if qa_indices is not None:
                qa_text = _convert_qa_rows(rows[1:], *qa_indices)
                if qa_text:
                    sections.append(f"# {sheet.title}\n\n{qa_text}")
                continue

            lines = [f"# {sheet.title}"]
            for row in rows[1:]:
                line = _row_to_line(header, list(row))
                if line:
                    lines.append(line)
            if len(lines) > 1:
                sections.append("\n".join(lines))
    finally:
        workbook.close()
    return "\n\n".join(sections)


def _has_content(row: Sequence[object]) -> bool:
    return any(cell is not None and str(cell).strip() for cell in row)


def _qa_sheet_records(rows: Sequence[Sequence[object]]) -> list[dict[str, str]] | None:
    """One sheet's rows keyed by canonical field, or None if it is not a QA table.

    每張工作表各自依 index 排好再接起來：多張表的 index 常常都從 1 開始，
    全部混在一起排的話，不同工作表的題目會交錯。
    """
    header = [_cell_text(rows[0], position) for position in range(len(rows[0]))]
    if _qa_column_indices(header) is None:
        return None
    columns: dict[str, int] = {}
    for position, name in enumerate(header):
        columns.setdefault(normalize_fieldname(name), position)
    records = [
        {
            field: _cell_text(row, columns[field])
            for field in (*_QA_TABLE_FIELDS, "index")
            if field in columns
        }
        for row in rows[1:]
    ]
    _sort_by_index(records)
    return [
        {field: value for field, value in record.items() if field != "index"}
        for record in records
    ]


def _qa_workbook_csv_bytes(path: Path) -> bytes | None:
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    records: list[dict[str, str]] = []
    has_qa_sheet = False
    try:
        for sheet in workbook.worksheets:
            rows = [row for row in sheet.iter_rows(values_only=True) if _has_content(row)]
            if not rows:
                continue
            sheet_records = _qa_sheet_records(rows)
            if sheet_records is None:
                return None
            has_qa_sheet = True
            records.extend(sheet_records)
    finally:
        workbook.close()
    if not has_qa_sheet:
        return None
    fieldnames = [
        field
        for field in _QA_TABLE_FIELDS
        if field in ("q", "a") or any(field in record for record in records)
    ]
    return _rows_to_csv_bytes(fieldnames, records)


def qa_table_ignored_columns(path: Path, file_bytes: bytes) -> list[str]:
    """Header names of an uploaded QA table that the import does not read, in order."""
    suffix = path.suffix.lower()
    sheets: list[list[str]] = []
    try:
        if suffix == ".csv":
            table = parse_csv_table(file_bytes)
            sheets = [[str(name).strip() for name in table[0]]] if table else []
        elif suffix == ".xlsx":
            import openpyxl

            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
            try:
                for sheet in workbook.worksheets:
                    first = next((row for row in sheet.iter_rows(values_only=True) if _has_content(row)), None)
                    if first:
                        sheets.append([_cell_text(first, position) for position in range(len(first))])
            finally:
                workbook.close()
    except Exception:  # noqa: BLE001 — a note is optional; the import itself already succeeded
        logger.warning("Failed to read the header of %s", path, exc_info=True)
        return []
    # 同一張表裡同一個欄位出現第二次（例如中英各一組問題、答案）只讀第一欄，後面的也算沒讀進去；
    # 不同工作表各有一組欄名是正常的。
    known = {*_QA_TABLE_FIELDS, "index"}
    ignored: list[str] = []
    for header in sheets:
        seen: set[str] = set()
        for name in header:
            field = normalize_fieldname(name)
            if name and (field not in known or field in seen):
                ignored.append(name)
            seen.add(field)
    return list(dict.fromkeys(ignored))


def qa_table_csv_bytes(path: Path, file_bytes: bytes) -> bytes | None:
    """Return an upload as QA CSV bytes when it is a QA table, otherwise ``None``.

    A CSV qualifies when it has question and answer columns. An Excel workbook
    qualifies when every non-empty sheet does; one other sheet makes the whole book
    an ordinary document. Never raises: an unreadable file is simply not a QA table.
    """
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            return file_bytes if is_qa_csv(file_bytes) else None
        if suffix == ".xlsx":
            return _qa_workbook_csv_bytes(path)
    except Exception:  # noqa: BLE001 — the ordinary conversion reports the failure
        logger.warning("Failed to read %s as a QA table", path, exc_info=True)
    return None


def _convert_pdf(path: Path) -> str:
    """Extract text from each PDF page via PyMuPDF, joined by blank lines."""
    import pymupdf

    pages: list[str] = []
    with pymupdf.open(path) as document:
        for page in document:
            # get_text() with no args returns the page's plain text; the stub
            # types it as a union, so coerce to str before stripping.
            text = str(page.get_text()).strip()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


# Suffix → extraction helper. Drives both dispatch and SUPPORTED_SUFFIXES.
_CONVERTERS = {
    ".md": _convert_text,
    ".txt": _convert_text,
    ".csv": _convert_csv,
    ".docx": _convert_docx,
    ".xlsx": _convert_xlsx,
    ".pdf": _convert_pdf,
}

SUPPORTED_SUFFIXES: frozenset[str] = frozenset(_CONVERTERS)


def convert_to_text(path: Path) -> str | None:
    """Extract readable text from a file.

    Returns ``None`` if the format is unsupported or extraction fails
    (caller will leave such files untouched). Never raises.
    """
    converter = _CONVERTERS.get(path.suffix.lower())
    if converter is None:
        return None

    try:
        text = converter(path)
    except Exception:  # noqa: BLE001 — any failure → leave file untouched
        logger.warning("Failed to extract text from %s", path, exc_info=True)
        return None

    if text is None or not text.strip():
        return None
    return text

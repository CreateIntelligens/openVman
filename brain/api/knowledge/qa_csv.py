"""
CSV utilities for openVman QA knowledge uploads.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Iterable


class UnsupportedQaCsvError(ValueError):
    """Raised when a CSV looks like Q&A data but lacks required columns."""


_QA_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_QA_METADATA_RE = re.compile(r"<!--\s*qa_metadata:\s*({.*?})\s*-->")


def _mask_code_block_headings(match: re.Match[str]) -> str:
    text = match.group(0)
    return "".join(" " if char != "\n" else "\n" for char in text)


def parse_qa_markdown(content: str) -> list[dict[str, Any]]:
    """Split a ``## question\\n\\nanswer`` markdown source into QA entries.

    Mirrors the block format produced by QaModal / ``convert_csv_to_qa_markdown``
    on the frontend and CSV-import side, so any QA source built through either
    path round-trips back into a flat list of ``{q, a, img, url}`` dicts. Code
    blocks are masked so ``##`` lines inside them are not parsed as headings.
    """
    cleaned_content = re.sub(
        r"```.*?```", _mask_code_block_headings, content, flags=re.DOTALL
    )
    headings = list(_QA_HEADING_RE.finditer(cleaned_content))
    entries: list[dict[str, Any]] = []
    for index, match in enumerate(headings):
        question = match.group(1).strip()
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
        body = content[start:end].strip()

        img_val = ""
        url_val = ""
        meta_match = _QA_METADATA_RE.search(body)
        if meta_match:
            try:
                meta_data = json.loads(meta_match.group(1))
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(meta_data, dict):
                    img_val = meta_data.get("img", "")
                    url_val = meta_data.get("url", "")
            body = _QA_METADATA_RE.sub("", body).strip()

        if question:
            entries.append({"q": question, "a": body, "img": img_val, "url": url_val})
    return entries


_FIELD_ALIASES: dict[str, list[str]] = {
    "q": ["q", "question", "問題", "问题", "題目", "题目", "項目", "项目"],
    "a": ["a", "answer", "答案", "回答", "回覆", "解答", "說明", "内容", "內容"],
    "img": ["img", "image", "圖片", "图片", "圖片 (image)", "image (圖片)"],
    "url": ["url", "link", "網址", "网址", "連結", "链接"],
    "index": ["index", "i", "順序"],
    "display": ["display", "d", "顯示"],
}


def _clean_string(s: str) -> str:
    cleaned = re.sub(r"[^\w]+", "", s)
    return cleaned.lower()


_CLEANED_FIELD_ALIASES = {
    canonical: [_clean_string(alias) for alias in aliases]
    for canonical, aliases in _FIELD_ALIASES.items()
}

_QA_CONTENT_FIELDS = ("q", "a", "img", "url")


def _dedupe_non_empty(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        value = (raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _normalize_fieldname(raw: str) -> str:
    cleaned_raw = _clean_string(raw)
    for canonical, cleaned_aliases in _CLEANED_FIELD_ALIASES.items():
        if cleaned_raw in cleaned_aliases:
            return canonical
    return raw.strip()


def _parse_csv_rows(file_bytes: bytes) -> tuple[list[str], list[dict[str, str]]] | None:
    encodings = ["utf-8-sig", "utf-8", "cp950", "big5", "gbk"]

    first_decodable_parsed = None

    for enc in encodings:
        try:
            text = file_bytes.decode(enc)
        except UnicodeDecodeError:
            continue

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            continue

        fieldnames: list[str] = []
        first_raw_for: dict[str, str] = {}
        matched_any_alias = False

        for raw in reader.fieldnames:
            canonical = _normalize_fieldname(raw)
            if canonical in _FIELD_ALIASES:
                matched_any_alias = True
            if canonical in first_raw_for:
                continue
            first_raw_for[canonical] = raw
            fieldnames.append(canonical)

        rows = [
            {canonical: row.get(first_raw_for[canonical], "") for canonical in fieldnames}
            for row in reader
        ]

        parsed_result = (fieldnames, rows)
        if first_decodable_parsed is None:
            first_decodable_parsed = parsed_result

        if matched_any_alias:
            return parsed_result

    return first_decodable_parsed


def validate_supported_qa_csv(file_bytes: bytes) -> None:
    """Reject malformed Q&A CSVs before they are stored.

    A CSV with Q&A-like columns but missing question or answer columns is
    almost certainly a bad export for this workspace. Plain non-Q&A CSVs are
    still allowed so existing generic knowledge-file behavior remains intact.
    """
    parsed = _parse_csv_rows(file_bytes)
    if parsed is None or not parsed[0]:
        raise UnsupportedQaCsvError("CSV is empty, invalid, or could not be parsed.")

    fieldnames, _ = parsed
    has_qa_fields = any(field in fieldnames for field in _QA_CONTENT_FIELDS)
    missing_required = [field for field in ("q", "a") if field not in fieldnames]
    if has_qa_fields and missing_required:
        missing = ", ".join(missing_required)
        raise UnsupportedQaCsvError(
            f"CSV must include q and a columns for Q&A uploads (missing: {missing})"
        )


def _rows_to_csv_bytes(fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _has_meaningful_qa_content(row: dict[str, str]) -> bool:
    return any((row.get(key) or "").strip() for key in _QA_CONTENT_FIELDS)


def _split_image_name_and_suffix(raw: str) -> tuple[str, str]:
    value = raw.replace("\\", "/").split("/")[-1]
    if "." not in value:
        return value, ""

    stem, ext = value.rsplit(".", 1)
    clean_ext = re.sub(r"[^A-Za-z0-9]+", "", ext).lower()
    return stem, f".{clean_ext}" if clean_ext else ""


def _image_filename_fragment(raw: str, fallback_index: int) -> str:
    value = (raw or "").strip()
    if "=" in value:
        value = value.split("=", 1)[-1].strip()
    value, suffix = _split_image_name_and_suffix(value)
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or f"row_{fallback_index:03d}"
    value = value if value.upper().startswith("IMG_") else f"IMG_{value}"
    return f"{value}{suffix}"


def _csv_image_value(raw: str) -> str:
    value = (raw or "").strip()
    if "=" in value:
        value = value.split("=")[-1]
    if "/" in value:
        value = value.split("/")[-1]
    return value


def _index_sort_value(raw: str) -> float:
    """Return numeric index, pushing blank/non-numeric values to the end."""
    try:
        return float((raw or "").strip())
    except (TypeError, ValueError):
        return float("inf")


def _sort_by_index(rows: list[dict]) -> None:
    rows.sort(key=lambda row: _index_sort_value(row.get("index", "")))


def _sort_and_renumber_by_index(rows: list[dict]) -> None:
    _sort_by_index(rows)
    for position, row in enumerate(rows, start=1):
        row["index"] = str(position)


def _has_preservable_indexes(rows: list[dict]) -> bool:
    """True when every row carries a distinct numeric index.

    Topics split across multiple CSV files (per-image `_IMG_` files) encode
    their cross-file question order in these values, so rewriting them to a
    per-file 1..N would lose the order chosen in the merged admin view.
    """
    values = [_index_sort_value(row.get("index", "")) for row in rows]
    finite = [value for value in values if value != float("inf")]
    return len(finite) == len(values) and len(set(finite)) == len(finite)


def normalize_qa_csv_rows(file_bytes: bytes) -> bytes | None:
    """Drop blank QA rows and sort by user index.

    Distinct numeric indexes are kept as-is (they may span sibling `_IMG_`
    files); blank/duplicate indexes fall back to renumbering 1..N.
    """
    parsed = _parse_csv_rows(file_bytes)
    if parsed is None:
        return None

    fieldnames, rows = parsed
    if "q" not in fieldnames:
        return None

    if "index" not in fieldnames:
        fieldnames = ["index", *fieldnames]

    meaningful_rows = [row for row in rows if _has_meaningful_qa_content(row)]
    if _has_preservable_indexes(meaningful_rows):
        _sort_by_index(meaningful_rows)
    else:
        _sort_and_renumber_by_index(meaningful_rows)

    return _rows_to_csv_bytes(fieldnames, meaningful_rows)


def split_qa_csv_by_image(file_bytes: bytes, filename: str) -> list[tuple[str, bytes]] | None:
    """Split a QA CSV into a main file plus one-image-per-file CSVs.

    Returns ``None`` when the CSV is not a QA CSV or it has no non-empty
    ``img`` values, allowing callers to preserve the original single-file flow.
    """
    parsed = _parse_csv_rows(file_bytes)
    if parsed is None:
        return None

    fieldnames, rows = parsed
    if "q" not in fieldnames or "img" not in fieldnames:
        return None

    main_rows: list[dict[str, str]] = []
    image_rows: list[tuple[dict[str, str], str]] = []
    for row in rows:
        if not _has_meaningful_qa_content(row):
            continue

        img_value = (row.get("img") or "").strip()
        if img_value:
            image_rows.append((row, img_value))
        else:
            main_rows.append(row)

    if not image_rows:
        return None

    path = Path(filename)
    suffix = path.suffix or ".csv"
    uploads: list[tuple[str, bytes]] = []

    if main_rows:
        uploads.append((path.name, _rows_to_csv_bytes(fieldnames, main_rows)))

    used_names: set[str] = {name for name, _ in uploads}
    for index, (row, img_value) in enumerate(image_rows, start=1):
        fragment = _image_filename_fragment(img_value, index)
        base = f"{path.stem}_{fragment}{suffix}"
        candidate = base
        counter = 1
        while candidate in used_names:
            stem = f"{path.stem}_{fragment}_row{index}"
            if counter > 1:
                stem = f"{stem}_{counter}"
            candidate = f"{stem}{suffix}"
            counter += 1
        used_names.add(candidate)
        uploads.append((candidate, _rows_to_csv_bytes(fieldnames, [row])))

    return uploads


def merge_csv_files(
    csv_contents: list[bytes],
    source_filenames: list[str] | None = None,
) -> list[dict]:
    """Parse multiple CSV bytes into unified list and sort by index.

    Returns a list of dicts with keys: index, q, a, img, url, source_file.
    When *source_filenames* is provided each row carries the filename it
    originated from so callers can map edits back to the correct file.
    """
    rows = []
    seen_q = set()
    for idx, file_bytes in enumerate(csv_contents):
        parsed = _parse_csv_rows(file_bytes)
        if parsed is None:
            continue
        _, parsed_rows = parsed

        src = source_filenames[idx] if source_filenames and idx < len(source_filenames) else None

        for row in parsed_rows:
            img_val = _csv_image_value(row.get("img") or "")
            q_val = (row.get("q") or "").strip()
            q_key = q_val.lower()
            if q_key in seen_q:
                continue

            merged_row = {
                "index": (row.get("index") or "").strip(),
                "q": q_val,
                "a": (row.get("a") or "").strip(),
                "img": img_val,
                "url": (row.get("url") or "").strip(),
                "source_file": src,
            }
            if any(merged_row[k] for k in _QA_CONTENT_FIELDS):
                seen_q.add(q_key)
                rows.append(merged_row)

    _sort_and_renumber_by_index(rows)
    return rows


_HIDDEN_DISPLAY_VALUES = frozenset({"false", "0", "否", "n", "no"})


def extract_hidden_from_csv(file_bytes: bytes) -> list[str]:
    """Extract questions explicitly marked hidden via the ``display`` column.

    Returns de-duplicated ``q`` values whose ``display`` cell is a falsey
    marker (see ``_HIDDEN_DISPLAY_VALUES``). Empty list when the CSV has no
    ``q``/``display`` columns or nothing is hidden — callers union this into
    any caller-supplied hidden_questions.
    """
    parsed = _parse_csv_rows(file_bytes)
    if parsed is None:
        return []

    fieldnames, rows = parsed
    if "q" not in fieldnames or "display" not in fieldnames:
        return []

    return _dedupe_non_empty(
        row.get("q")
        for row in rows
        if (row.get("display") or "").strip().lower() in _HIDDEN_DISPLAY_VALUES
    )

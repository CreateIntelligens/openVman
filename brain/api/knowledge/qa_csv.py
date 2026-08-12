"""
CSV utilities for openVman QA knowledge uploads.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any


_QA_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_QA_METADATA_RE = re.compile(r"<!--\s*qa_metadata:\s*({.*?})\s*-->")


def _mask_code_block_headings(match: re.Match[str]) -> str:
    text = match.group(0)
    return "".join(" " if char != "\n" else "\n" for char in text)


def parse_qa_markdown(content: str) -> list[dict[str, Any]]:
    """Split a ``## question\\n\\nanswer`` markdown source into QA entries.

    Mirrors the block format produced by ``qa_markdown_block`` and
    ``convert_csv_to_qa_markdown``, so QA sources round-trip back into a flat
    list of ``{q, a, img, url, hidden}`` dicts. Code blocks are masked so
    ``##`` lines inside them are not parsed as headings.
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
        hidden_val = False
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
                    hidden_val = bool(meta_data.get("hidden", False))
            body = _QA_METADATA_RE.sub("", body).strip()

        if question:
            entries.append(
                {
                    "q": question,
                    "a": body,
                    "img": img_val,
                    "url": url_val,
                    "hidden": hidden_val,
                }
            )
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


def normalize_fieldname(raw: str) -> str:
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
            canonical = normalize_fieldname(raw)
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


def _rows_to_csv_bytes(fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _has_meaningful_qa_content(row: dict[str, str]) -> bool:
    return any((row.get(key) or "").strip() for key in _QA_CONTENT_FIELDS)


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


_HIDDEN_DISPLAY_VALUES = frozenset({"false", "0", "否", "n", "no"})


def is_qa_csv(file_bytes: bytes) -> bool:
    """Return True if the CSV contains Q&A content fields (both 'q' and 'a')."""
    parsed = _parse_csv_rows(file_bytes)
    if parsed is None:
        return False
    fieldnames, _ = parsed
    return "q" in fieldnames and "a" in fieldnames


def parse_qa_csv(file_bytes: bytes) -> list[dict[str, Any]]:
    """Parse QA CSV bytes into the same entry shape as QA markdown."""
    parsed = _parse_csv_rows(file_bytes)
    if parsed is None:
        return []

    _, rows = parsed
    entries: list[dict[str, Any]] = []
    for row in rows:
        question = (row.get("q") or "").strip()
        answer = (row.get("a") or "").strip()
        if not question and not answer:
            continue
        entries.append(
            {
                "q": question or "未命名問題",
                "a": answer,
                "img": extract_image_id(row.get("img") or ""),
                "url": (row.get("url") or "").strip(),
                "hidden": (
                    (row.get("display") or "").strip().lower()
                    in _HIDDEN_DISPLAY_VALUES
                ),
            }
        )
    return entries


def serialize_qa_csv(entries: list[dict[str, Any]]) -> str:
    """Serialize merged-editor QA entries without changing a CSV source to markdown."""
    fieldnames = ["index", "q", "a", "img", "url", "display"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for position, entry in enumerate(entries, start=1):
        writer.writerow(
            {
                "index": entry.get("index") or str(position),
                "q": entry.get("q") or "",
                "a": entry.get("a") or "",
                "img": extract_image_id(entry.get("img") or ""),
                "url": entry.get("url") or "",
                "display": "false" if entry.get("hidden") else "true",
            }
        )
    return buffer.getvalue()


def extract_image_id(raw: str) -> str:
    value = (raw or "").strip()
    if "=" in value:
        value = value.split("=")[-1].strip()
    if "/" in value:
        value = value.split("/")[-1].strip()
    return value


def qa_markdown_block(
    question: str, answer: str, img: str = "", url: str = "", hidden: bool = False
) -> str:
    metadata: dict[str, Any] = {"img": extract_image_id(img), "url": url}
    if hidden:
        metadata["hidden"] = True
    metadata_str = json.dumps(metadata, ensure_ascii=False)
    return f"## {question}\n\n{answer}\n<!-- qa_metadata: {metadata_str} -->"


def convert_csv_to_qa_markdown(csv_bytes: bytes) -> str:
    """Convert a QA CSV into markdown blocks with HTML comment metadata.

    Rows are normalized first (blank rows dropped, sorted by user index) so
    the markdown is self-contained: per-question ``hidden`` state from the
    ``display`` column travels inside ``qa_metadata`` instead of a side
    channel, letting attach-time parsing recover it from the file alone.
    """
    normalized = normalize_qa_csv_rows(csv_bytes)
    if normalized is not None:
        csv_bytes = normalized
    blocks = [
        qa_markdown_block(
            entry["q"],
            entry["a"],
            entry["img"],
            entry["url"],
            entry["hidden"],
        )
        for entry in parse_qa_csv(csv_bytes)
    ]
    return "\n\n".join(blocks)

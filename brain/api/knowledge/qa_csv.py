"""
CSV utilities for openVman QA knowledge uploads.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from typing import Any


_QA_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_QA_METADATA_RE = re.compile(r"<!--\s*qa_metadata:\s*({.*?})\s*-->")
_CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp950", "big5", "gbk")


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
    "language": ["language", "lang", "語言", "语言"],
}

_ROW_LANGUAGES: dict[str, str] = {
    "zh": "zh", "zhtw": "zh", "zhhant": "zh", "中文": "zh", "華語": "zh", "繁體中文": "zh",
    "en": "en", "english": "en", "英文": "en",
    "es": "es", "español": "es", "espanol": "es", "spanish": "es", "西文": "es", "西班牙文": "es",
    "ja": "ja", "日本語": "ja", "日文": "ja",
    "ko": "ko", "한국어": "ko", "韓文": "ko",
    "nan": "nan", "台語": "nan", "閩南語": "nan",
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
    first_decodable_parsed = None

    for enc in _CSV_ENCODINGS:
        try:
            text = file_bytes.decode(enc)
        except UnicodeDecodeError:
            continue

        reader = csv.DictReader(io.StringIO(text, newline=""))
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


def append_qa_csv_rows(file_bytes: bytes, entries: list[dict[str, Any]]) -> str:
    """Append QA entries to a CSV, keeping its header, rows and extra columns.

    不走 ``parse_qa_csv`` → ``serialize_qa_csv``：那條路會丟掉 index 與自訂欄位，
    而拆成多檔的主題靠 index 記跨檔順序。新列的 index 接在現有最大值之後；
    只有新列真的用到時才新增 img／url／display 欄。檔案必須是 UTF-8。
    """
    table = list(csv.reader(io.StringIO(file_bytes.decode("utf-8-sig"), newline="")))
    if not table:
        raise ValueError("CSV 沒有標題列")
    header, rows = table[0], table[1:]
    column_of: dict[str, int] = {}
    for position, raw in enumerate(header):
        column_of.setdefault(normalize_fieldname(raw), position)
    if "q" not in column_of or "a" not in column_of:
        raise ValueError("CSV 缺少問題或回答欄位")

    def _add_column(canonical: str) -> None:
        column_of[canonical] = len(header)
        header.append(canonical)
        for row in rows:
            if row:
                row.extend([""] * (len(header) - len(row)))

    if "img" not in column_of and any(extract_image_id(e.get("img") or "") for e in entries):
        _add_column("img")
    if "url" not in column_of and any((e.get("url") or "").strip() for e in entries):
        _add_column("url")
    if "display" not in column_of and any(e.get("hidden") for e in entries):
        _add_column("display")

    next_index = 0
    if "index" in column_of:
        cells = (row[column_of["index"]] for row in rows if len(row) > column_of["index"])
        numeric = [v for v in map(_index_sort_value, cells) if math.isfinite(v)]
        next_index = int(max(numeric, default=len(rows))) + 1

    for entry in entries:
        values = {
            "q": entry.get("q") or "",
            "a": entry.get("a") or "",
            "img": extract_image_id(entry.get("img") or ""),
            "url": (entry.get("url") or "").strip(),
            "display": "false" if entry.get("hidden") else "true",
        }
        if "index" in column_of:
            values["index"] = str(next_index)
            next_index += 1
        row = [""] * len(header)
        for canonical, value in values.items():
            if canonical in column_of:
                row[column_of[canonical]] = value
        rows.append(row)

    return _write_csv_table([header, *rows])


def _write_csv_table(rows: list[list[str]]) -> str:
    """Serialize a raw CSV table.

    Python 3.11 的 csv.writer 只替 lineterminator 裡的字元加引號，格子裡單獨的 \\r 會原樣
    寫出，讀回來就斷成兩列，所以統一成 \\n。
    """
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerows(
        [[cell.replace("\r\n", "\n").replace("\r", "\n") for cell in row] for row in rows]
    )
    return buffer.getvalue()


def _decode_qa_csv_table(file_bytes: bytes) -> list[list[str]]:
    """Read a QA CSV as raw rows, in the encoding whose header has QA columns."""
    for encoding in _CSV_ENCODINGS:
        try:
            text = file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
        table = list(csv.reader(io.StringIO(text, newline="")))
        if table and {"q", "a"} <= {normalize_fieldname(raw) for raw in table[0]}:
            return table
    raise ValueError("CSV 缺少問題或回答欄位")


def parse_csv_table(file_bytes: bytes) -> list[list[str]]:
    """Raw rows of a QA CSV, header first."""
    return _decode_qa_csv_table(file_bytes)


def _place_rows(
    rows: list[Any],
    question_of: Any,
    updates: list[dict[str, Any]],
    removed: set[str],
    build_row: Any,
    keep_positions: bool = False,
) -> list[Any]:
    """Put updated rows back into the slots they came from, leaving every other row alone.

    同題重複時對應最後一列，和合併檢視顯示的那列相同。多出來的新題接在這批題目最後一個
    位置之後，不接到檔尾，才不會跑到別的節點的題目後面。

    ``keep_positions``：每列留在自己原本的位置，只換內容。檔案分給多個節點時要這樣，
    同一題在兩個節點的順序可能不同，照這個節點的順序重排會改到另一個節點的選單。
    """
    last_position = {question_of(row): position for position, row in enumerate(rows)}
    sources = {
        update["match"]: last_position[update["match"]]
        for update in updates
        if update.get("match") in last_position
    }
    built = [
        (
            sources.get(update.get("match")),
            build_row(update, rows[sources[update["match"]]] if update.get("match") in sources else None),
        )
        for update in updates
    ]
    if keep_positions:
        by_position = {position: row for position, row in built if position is not None}
        fresh = [row for position, row in built if position is None]
    else:
        slots = sorted(sources.values())
        by_position = dict(zip(slots, (row for _, row in built)))
        fresh = [row for _, row in built][len(slots):]
    result: list[Any] = []
    last_slot = -1
    for position, row in enumerate(rows):
        if position in by_position:
            result.append(by_position[position])
            last_slot = len(result)
        elif question_of(row) not in removed:
            result.append(row)
    insert_at = last_slot if last_slot >= 0 else len(result)
    result[insert_at:insert_at] = fresh
    return result


def rewrite_qa_csv(
    file_bytes: bytes,
    updates: list[dict[str, Any]],
    removed: set[str],
) -> str:
    """Apply one node's edits to a CSV without touching rows the node does not own.

    ``updates`` is the node's rows in screen order; ``match`` names the question
    a row replaces (absent for a new row). Only cells whose meaning changed are
    rewritten, so extra columns and other nodes' rows stay byte-for-byte.
    """
    table = _decode_qa_csv_table(file_bytes)
    header, rows = table[0], table[1:]
    column_of: dict[str, int] = {}
    for position, raw in enumerate(header):
        column_of.setdefault(normalize_fieldname(raw), position)

    def _add_column(canonical: str) -> None:
        column_of[canonical] = len(header)
        header.append(canonical)
        for row in rows:
            if row:
                row.extend([""] * (len(header) - len(row)))

    def _cell(row: list[str], canonical: str) -> str:
        position = column_of.get(canonical)
        return row[position] if position is not None and position < len(row) else ""

    if "index" not in column_of:
        _add_column("index")
    if "img" not in column_of and any(extract_image_id(u.get("img") or "") for u in updates):
        _add_column("img")
    if "url" not in column_of and any((u.get("url") or "").strip() for u in updates):
        _add_column("url")
    if "display" not in column_of and any(u.get("hidden") for u in updates):
        _add_column("display")

    def _question_of(row: list[str]) -> str:
        return _cell(row, "q").strip()

    matched = {u["match"] for u in updates if u.get("match")}
    last_position = {_question_of(row): position for position, row in enumerate(rows)}
    matched_positions = {last_position[q] for q in matched if q in last_position}
    has_other_rows = any(
        position not in matched_positions and _question_of(row) not in removed and any(row)
        for position, row in enumerate(rows)
    )

    indexes: list[str] = []
    if has_other_rows:
        # 檔案分給多個節點：每列保留原本的 index，新題排在最大值之後。順序記在節點上。
        all_values = [
            value
            for value in (_index_sort_value(_cell(row, "index")) for row in rows)
            if math.isfinite(value)
        ]
        next_index = int(max(all_values, default=0)) + 1
        for update in updates:
            position = last_position.get(update.get("match")) if update.get("match") else None
            if position is not None:
                indexes.append(_cell(rows[position], "index"))
            else:
                indexes.append(str(next_index))
                next_index += 1
    else:
        # 用畫面上的位置，不信任 client 帶的 index：樹上拖題時送回來的還是舊值。
        indexes = [str(u.get("position") or position) for position, u in enumerate(updates, start=1)]
    index_of = {id(update): index for update, index in zip(updates, indexes)}

    def _build_row(update: dict[str, Any], existing: list[str] | None) -> list[str]:
        row = list(existing) if existing is not None else [""] * len(header)
        row.extend([""] * (len(header) - len(row)))

        def _put(canonical: str, value: str, unchanged: bool = False) -> None:
            if canonical in column_of and not (existing is not None and unchanged):
                row[column_of[canonical]] = value

        q, a = update.get("q") or "", update.get("a") or ""
        img = extract_image_id(update.get("img") or "")
        url = (update.get("url") or "").strip()
        hidden = bool(update.get("hidden"))
        current_display = _cell(row, "display").strip().lower()
        _put("q", q, _cell(row, "q").strip() == q)
        _put("a", a, _cell(row, "a").strip() == a)
        _put("img", img, extract_image_id(_cell(row, "img")) == img)
        _put("url", url, _cell(row, "url").strip() == url)
        _put(
            "display",
            "false" if hidden else "true",
            (current_display in _HIDDEN_DISPLAY_VALUES) == hidden,
        )
        _put("index", index_of[id(update)])
        return row

    return _write_csv_table(
        [header, *_place_rows(rows, _question_of, updates, removed, _build_row, keep_positions=has_other_rows)]
    )


def qa_markdown_preamble(content: str) -> str:
    """Text before the first question heading."""
    masked = re.sub(r"```.*?```", _mask_code_block_headings, content, flags=re.DOTALL)
    first = _QA_HEADING_RE.search(masked)
    return (content[: first.start()] if first else content).strip()


def rewrite_qa_markdown(
    content: str,
    updates: list[dict[str, Any]],
    removed: set[str],
) -> str:
    """Markdown counterpart of ``rewrite_qa_csv``.

    沒改到的段落照原文留著：重新組出來會把別的節點的自訂 metadata 與格式洗掉。
    """
    masked = re.sub(r"```.*?```", _mask_code_block_headings, content, flags=re.DOTALL)
    headings = list(_QA_HEADING_RE.finditer(masked))
    preamble = qa_markdown_preamble(content)
    blocks: list[tuple[str, str, dict[str, Any]]] = []
    for position, heading in enumerate(headings):
        end = headings[position + 1].start() if position + 1 < len(headings) else len(content)
        raw = content[heading.start():end].strip()
        parsed = parse_qa_markdown(raw)
        if parsed:
            blocks.append((parsed[0]["q"].strip(), raw, parsed[0]))

    def _values(entry: dict[str, Any]) -> tuple[str, str, str, str, bool]:
        return (
            entry["q"].strip(),
            entry["a"].strip(),
            extract_image_id(entry.get("img") or ""),
            (entry.get("url") or "").strip(),
            bool(entry.get("hidden", False)),
        )

    def _build_block(
        update: dict[str, Any], existing: tuple[str, str, dict[str, Any]] | None,
    ) -> tuple[str, str, dict[str, Any]]:
        if existing is not None and _values(existing[2]) == _values(update):
            return existing
        raw = qa_markdown_block(
            update["q"],
            update["a"],
            update.get("img") or "",
            update.get("url") or "",
            bool(update.get("hidden", False)),
        )
        return (update["q"], raw, update)

    matched = {update.get("match") for update in updates if update.get("match")}
    shared = any(block[0] not in matched and block[0] not in removed for block in blocks)
    placed = _place_rows(blocks, lambda block: block[0], updates, removed, _build_block, keep_positions=shared)
    return "\n\n".join([preamble, *(block[1] for block in placed)] if preamble else [block[1] for block in placed])


def normalize_row_language(raw: str) -> str | None:
    """Language code for a CSV ``language`` cell; unknown values count as unlabelled."""
    return _ROW_LANGUAGES.get(_clean_string(raw or ""))


def label_qa_csv_languages(file_bytes: bytes, detect: Any) -> tuple[str, dict[str, int]]:
    """Fill the ``language`` column of rows where it is blank.

    Whatever a person wrote stays, even a value this code does not know, so a
    correction survives a later run. ``detect`` gets the question and answer text
    and returns a code.
    """
    table = _decode_qa_csv_table(file_bytes)
    header, rows = table[0], table[1:]
    column_of: dict[str, int] = {}
    for position, raw in enumerate(header):
        column_of.setdefault(normalize_fieldname(raw), position)
    if "language" not in column_of:
        # 列比標題長時，多出來的格子不能被新欄蓋掉。
        width = max((len(row) for row in rows), default=len(header))
        header.extend([""] * (width - len(header)))
        column_of["language"] = len(header)
        header.append("language")

    counts: dict[str, int] = {}
    position = column_of["language"]
    for row in rows:
        if not any(row):
            continue
        row.extend([""] * (len(header) - len(row)))
        language = row[position].strip()
        if not language:
            language = detect(f"{row[column_of['q']]} {row[column_of['a']]}")
            row[position] = language
        counts[language] = counts.get(language, 0) + 1

    return _write_csv_table([header, *rows]), counts


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
# 只有答案、沒有題目的列，解析時用這個名字代替。
UNTITLED_QUESTION = "未命名問題"


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
                "q": question or UNTITLED_QUESTION,
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
    if any(entry.get("language") for entry in entries):
        fieldnames.append("language")
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
                **({"language": entry.get("language") or ""} if "language" in fieldnames else {}),
            }
        )
    return buffer.getvalue()


def qa_entry_values(entries: list[dict[str, Any]]) -> list[tuple[str, str, str, str, bool]]:
    """Comparable values of parsed QA entries, for checking content reads back unchanged."""
    return [
        (
            entry["q"].strip(),
            entry["a"].strip(),
            extract_image_id(entry.get("img") or ""),
            (entry.get("url") or "").strip(),
            bool(entry.get("hidden", False)),
        )
        for entry in entries
    ]


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

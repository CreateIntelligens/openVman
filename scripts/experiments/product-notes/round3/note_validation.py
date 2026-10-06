"""Validate notes against raw catalog rows without filter-engine code.

The caller parses YAML from the same Markdown and passes that mapping here.
This module uses only the standard library so it can be injected into the
existing isolated container process without installing dependencies.
"""

import math
import re


SOURCE_PATH = "knowledge/EVAK_CATALOG.md"
MODEL_NAMES = (
    "80EDW-5.20S/T", "80EDW-5.30S/T", "100EDW-5.30S/T",
    "80EDW-5.50T", "100EDW-5.50T", "50EUB-M-5.20S",
    "80EUB-M-5.20S", "50EUB-M-5.20T", "80EUB-M-5.20T",
    "50EUB-M-5.30T", "80EUB-M-5.30T", "80EUB-M-5.50T",
    "100EUB-M-5.50T", "80EUB-M-5.75T", "100EUB-M-5.75T",
)
NOTE_NAMES = {model.replace("/", "-"): model for model in MODEL_NAMES}
PHASE_FOOTNOTE = (
    "> 1. 電源標記：» S 代表單相（Single Phase）；"
    "» T 代表三相（Three Phase）。"
)
NUMBER = r"[0-9]+(?:\.[0-9]+)?"
SPEC_FIELDS = (
    "model", "series", "hp", "kw", "outlet_inch", "rated_head_m",
    "rated_flow_lpm", "max_head_m", "max_flow_lpm", "solids_mm",
    "phase", "current_1ph_a", "current_3ph_a", "weight_1ph_kg",
    "weight_3ph_kg",
)


def _compact(value):
    return re.sub(r"\s+", "", value)


def _number(cell, unit):
    match = re.fullmatch(rf"\s*({NUMBER})\s*{unit}\s*", cell)
    if not match:
        raise ValueError(f"無法解析原表數值或單位：{cell!r}")
    return float(match[1])


def _optional_number(cell, unit):
    return None if cell.strip() == "-" else _number(cell, unit)


def _split(cell, delimiter):
    parts = cell.split(delimiter)
    if len(parts) != 2:
        raise ValueError(f"原表欄位必須含兩個值：{cell!r}")
    return parts


def _parse_row(row):
    raw = row["row"].strip()
    if not raw.startswith("|") or not raw.endswith("|"):
        raise ValueError("原表列必須是完整 Markdown 表格列")
    cells = [cell.strip() for cell in raw[1:-1].split("|")]
    if len(cells) != 9:
        raise ValueError("原表列必須有九個欄位")
    if cells[0] != row["model"] or cells[0] not in MODEL_NAMES:
        raise ValueError("原表首欄與提供型號不符或型號不在凍結的十五列")
    series = "EDW" if "EDW" in cells[0] else "EUB-M"
    if row["series"] != series:
        raise ValueError("提供系列與原表型號不符")
    hp_cell, kw_cell = _split(cells[1], "/")
    rated_head, rated_flow = _split(cells[3], "@")
    max_head, max_flow = _split(cells[4], "@")
    current_cells = (_split(cells[6], "/") if series == "EDW"
                     else (cells[6], cells[7]))
    weight_cells = _split(cells[7 if series == "EDW" else 8], "/")
    currents = [_optional_number(cell, "A") for cell in current_cells]
    weights = [_optional_number(cell, "kg") for cell in weight_cells]
    phases = [phase for phase, current in zip((1, 3), currents)
              if current is not None]
    if not phases:
        raise ValueError("原表沒有任何有效電源相數")
    return {
        "model": cells[0], "series": series,
        "hp": _number(hp_cell, "HP"), "kw": _number(kw_cell, "kW"),
        "outlet_inch": _number(cells[2], '"'),
        "rated_head_m": _number(rated_head, "m"),
        "rated_flow_lpm": _number(rated_flow, "LPM"),
        "max_head_m": _number(max_head, "m"),
        "max_flow_lpm": _number(max_flow, "LPM"),
        "solids_mm": _number(cells[5], "mm"),
        "phase": phases if len(phases) > 1 else phases[0],
        "current_1ph_a": currents[0], "current_3ph_a": currents[1],
        "weight_1ph_kg": weights[0], "weight_3ph_kg": weights[1],
    }


def parse_source_specs(table_rows):
    """Return round2-compatible records, independently parsing each raw row.

    Cached ``cells`` are deliberately not used as the numeric authority.
    Malformed source input raises ValueError; validate_note turns that into
    a detailed failed validation instead of hiding it behind an assertion.
    """
    records = []
    for row in table_rows:
        records.append({"frontmatter": _parse_row(row), "line": row["line"],
                        "page": row["page"]})
    return records


def _json_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return repr(value)


def _matches(actual, expected):
    if expected is None:
        return actual is None
    if isinstance(expected, str):
        return isinstance(actual, str) and actual == expected
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(actual) == len(expected)
                and all(type(value) is int for value in actual)
                and actual == expected)
    return (type(actual) in (int, float)
            and (type(actual) is int or math.isfinite(actual))
            and actual == expected)


def _source_pages(lines):
    pages = {}
    page = None
    for line_no, text in enumerate(lines, 1):
        heading = re.match(r"^##\s+第\s*([0-9]+)\s*頁(?:[：:]|\s|$)", text)
        if heading:
            page = int(heading[1])
        pages[line_no] = page
    return pages


def validate_note(markdown, frontmatter, row, source):
    """Return JSON-safe status, every validation error, and audit details.

    ``row`` is one raw table_rows.json entry, ``source`` the complete frozen
    source_catalog.md text, and ``frontmatter`` YAML already parsed by caller.
    No files are read or written, and the generated Markdown is never edited.
    """
    errors = []
    checked = {"fields": [], "citations": [], "body": [], "wikilinks": []}

    def error(code, field, expected, actual, **context):
        errors.append(_json_value({
            "code": code, "field": field, "expected": expected,
            "actual": actual, **context,
        }))

    def finish():
        return {"status": "failed" if errors else "passed",
                "model": row.get("model"), "errors": errors,
                "checked": _json_value(checked)}

    try:
        expected = _parse_row(row)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        error("source_parse", "row", "可解析的凍結原表列", str(exc))
        return finish()
    if not isinstance(frontmatter, dict):
        error("frontmatter_type", "frontmatter", "mapping", frontmatter)
        frontmatter = {}
    for field in SPEC_FIELDS:
        actual = frontmatter.get(field)
        match = field in frontmatter and _matches(actual, expected[field])
        # Phase is categorical: 1.0 and True must not become valid phase 1.
        if field == "phase" and not isinstance(expected[field], list):
            match = match and type(actual) is int
        checked["fields"].append({"field": field, "expected": expected[field],
                                  "actual": actual, "match": match,
                                  "source_line": row["line"]})
        if not match:
            error("spec_value", field, expected[field], actual,
                  source_line=row["line"], present=field in frontmatter)
    for field in frontmatter.keys() - set(SPEC_FIELDS) - {"source"}:
        error("unknown_field", str(field), "凍結的十六個 frontmatter 欄位",
              frontmatter[field])

    lines = source.splitlines() if isinstance(source, str) else []
    pages = _source_pages(lines)

    def citation_check(page, line, kind):
        valid_position = (type(page) is int and type(line) is int
                          and 1 <= line <= len(lines))
        actual_text = lines[line - 1] if valid_position else None
        actual_page = pages.get(line) if valid_position else None
        checked["citations"].append({"kind": kind, "page": page,
                                     "line": line, "actual_page": actual_page,
                                     "quote": actual_text})
        if not valid_position:
            error("citation_position", kind, "有效的整數頁碼與行號",
                  {"page": page, "line": line})
        elif page != actual_page:
            error("citation_page", kind, actual_page, page, source_line=line)
        return actual_text

    raw_text = citation_check(row["page"], row["line"], "raw_row")
    if raw_text != row["row"]:
        error("source_row", "row", row["row"], raw_text,
              source_line=row["line"])
    src = frontmatter.get("source")
    if not isinstance(src, dict):
        error("source_type", "source", "mapping", src)
        src = {}
    for field, value in (("path", SOURCE_PATH), ("page", row["page"]),
                         ("row_line", row["line"])):
        actual = src.get(field)
        match = (_matches(actual, value) if field == "path" else
                 type(actual) is int and actual == value)
        if not match:
            error("source_metadata", f"source.{field}", value, actual)
    for field in src.keys() - {"path", "page", "row_line", "footnotes"}:
        error("unknown_field", f"source.{field}", "已定義的來源欄位", src[field])
    cited_text = citation_check(src.get("page"), src.get("row_line"),
                                "source.row_line")
    if cited_text is not None:
        first_cell = (cited_text.strip().split("|")[1].strip()
                      if cited_text.strip().startswith("|") else None)
        if first_cell != expected["model"]:
            error("citation_model", "source.row_line", expected["model"],
                  first_cell, quote=cited_text)
    footnotes = src.get("footnotes")
    if not isinstance(footnotes, list):
        error("footnotes_type", "source.footnotes", "list（無註腳為 []）",
              footnotes)
        footnotes = []
    valid_footnotes = []
    for index, footnote in enumerate(footnotes):
        field = f"source.footnotes[{index}]"
        if not isinstance(footnote, dict):
            error("footnote_type", field, "{page: 9, line: 208}", footnote)
            continue
        page, line = footnote.get("page"), footnote.get("line")
        text = citation_check(page, line, field)
        allowed = (expected["series"] == "EDW" and type(page) is int
                   and page == 9 and type(line) is int and line == 208
                   and set(footnote) == {"page", "line"})
        if not allowed:
            error("footnote_reference", field,
                  {"page": 9, "line": 208} if expected["series"] == "EDW"
                  else "此系列沒有提供註腳，不可引用", footnote)
        elif text is None or _compact(text) != _compact(PHASE_FOOTNOTE):
            error("footnote_content", field, PHASE_FOOTNOTE, text)
        else:
            valid_footnotes.append({"page": page, "line": line})
    if len(valid_footnotes) != len({(f["page"], f["line"])
                                    for f in valid_footnotes}):
        error("footnote_duplicate", "source.footnotes", "不重複的註腳",
              footnotes)
    if (expected["phase"] == [1, 3]
            and {"page": 9, "line": 208} not in valid_footnotes):
        error("footnote_required", "source.footnotes",
              {"page": 9, "line": 208}, footnotes)

    if not isinstance(markdown, str):
        error("markdown_type", "markdown", "str", markdown)
        return finish()
    boundary = re.match(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)",
                        markdown, re.DOTALL)
    if not boundary:
        error("frontmatter_delimiters", "markdown", "以 --- 包住 YAML 開頭",
              markdown[:120])
        return finish()
    body_lines = []
    heading_names = {
        expected["model"], expected["model"] + " 規格",
        expected["model"] + " 產品筆記", expected["model"] + " 規格筆記",
        "規格", "規格摘要", "額定與最大值", "出處", "相關連結",
    }
    for text in markdown[boundary.end():].splitlines():
        if _compact(text) in ("相關連結", "相關連結：", "相關連結:"):
            continue
        heading = re.fullmatch(r"#{1,6}\s+(.+?)\s*", text)
        if heading:
            allowed_headings = {_compact(value) for value in heading_names}
            heading_label = _compact(heading[1])
            if heading_label in ("相關連結：", "相關連結:"):
                heading_label = "相關連結"
            if heading_label not in allowed_headings:
                error("body_heading", "heading", sorted(heading_names), text)
            continue
        if "[[" in text or "]]" in text:
            links = re.findall(r"\[\[([^\[\]\n]+)\]\]", text)
            for link in links:
                parts = link.split("|")
                target = parts[0]
                stem = target[:-3] if target.endswith(".md") else target
                linked_model = NOTE_NAMES.get(stem)
                valid = (linked_model is not None and len(parts) <= 2
                         and (len(parts) == 1 or parts[1] in
                              (linked_model, stem)))
                checked["wikilinks"].append({"target": target,
                                             "valid": valid})
                if not valid:
                    error("wikilink_target", "wikilink", NOTE_NAMES, link)
            # A Markdown list marker is layout, while words outside links
            # remain claims and must still fail the content allowlist.
            link_text = re.sub(r"^\s*[-*+]\s+", "", text)
            remainder = _compact(re.sub(
                r"\[\[([^\[\]\n]+)\]\]", "", link_text,
            ))
            remainder = re.sub(r"^相關連結[:：]", "", remainder)
            if not links or re.sub(r"[，,、；;。]", "", remainder):
                error("body_extra", "related_links", "僅含相關連結與 wikilinks",
                      text)
            continue
        body_lines.append(text)
    body = _compact("\n".join(body_lines)).replace(":", "：")
    definitions = (
        ("rated", rf"額定點：揚程({NUMBER})m，流量({NUMBER})LPM（同一工作點）。",
         ("rated_head_m", "rated_flow_lpm")),
        ("max_head", rf"最大揚程：({NUMBER})m。", ("max_head_m",)),
        ("max_flow", rf"最大流量：({NUMBER})LPM。", ("max_flow_lpm",)),
        ("independent_maxima", "兩者是各自的極限值，不是同一個工作點。", ()),
    )
    positions = []
    for label, pattern, fields in definitions:
        matches = list(re.finditer(pattern, body))
        checked["body"].append({"block": label, "count": len(matches)})
        if len(matches) != 1:
            error("body_required", label, "恰好出現一次規定句型", len(matches))
        for match in matches:
            positions.append(match.span())
            for field, value in zip(fields, match.groups()):
                if float(value) != expected[field]:
                    error("body_number", field, expected[field], value,
                          source_line=row["line"])
    citation_pattern = (r"出處：第([0-9]+)頁，L([0-9]+)"
                        r"(?:；註腳：第([0-9]+)頁，L([0-9]+))?。")
    body_citations = list(re.finditer(citation_pattern, body))
    if len(body_citations) != 1:
        error("body_citation_required", "body.source", "恰好一個完整出處句",
              len(body_citations))
    for match in body_citations:
        positions.append(match.span())
        page, line = int(match[1]), int(match[2])
        citation_check(page, line, "body.row_line")
        if (page, line) != (row["page"], row["line"]):
            error("body_citation", "body.source",
                  {"page": row["page"], "line": row["line"]},
                  {"page": page, "line": line})
        body_footnotes = ([{"page": int(match[3]), "line": int(match[4])}]
                          if match[3] is not None else [])
        if body_footnotes != footnotes:
            error("body_footnotes", "body.source.footnotes", footnotes,
                  body_footnotes)
    # The allowlist prevents correct sentences from masking extra claims.
    remaining = body
    for start, end in sorted(positions, reverse=True):
        remaining = remaining[:start] + remaining[end:]
    if remaining:
        error("body_extra", "body", "僅含標題、四句規格、出處與相關連結",
              remaining)
    checked["body_remaining"] = remaining
    return finish()

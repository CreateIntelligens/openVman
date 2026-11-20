"""Read source documents for quick-QA category mounts."""

from __future__ import annotations

from typing import Any

from knowledge.qa_csv import (
    UNTITLED_QUESTION,
    extract_image_id,
    normalize_qa_csv_rows,
    parse_qa_csv,
    parse_qa_markdown,
)
from knowledge.workspace import resolve_workspace_document


def _parse_source_items(source_path: str, project_id: str = "default") -> list[dict[str, Any]]:
    doc_path = resolve_workspace_document(source_path, project_id)
    if not doc_path.exists():
        return []
    # CSV 直接解析：轉成 Markdown 再切的話，答案裡的 ## 行和多行題目會變成別的題目。
    if source_path.lower().endswith(".csv"):
        csv_bytes = doc_path.read_bytes()
        return parse_qa_csv(normalize_qa_csv_rows(csv_bytes) or csv_bytes)
    return parse_qa_markdown(doc_path.read_text(encoding="utf-8-sig", errors="ignore"))


def _build_entries_for_source(
    source_path: str, project_id: str = "default"
) -> list[dict[str, Any]]:
    """Parse a QA markdown or CSV doc into node qa_entries (deduped by question)."""
    # 同題重複時取最後一列，和合併檢視顯示、存檔改寫的那列相同；排序留在第一次出現的位置。
    entries: dict[str, dict[str, Any]] = {}
    for item in _parse_source_items(source_path, project_id):
        question = item["q"].strip()
        if not question or question == UNTITLED_QUESTION:
            continue
        image_id = extract_image_id(item.get("img") or "")
        entries[question] = {
            "question": question,
            "source_path": source_path,
            "hidden": bool(item.get("hidden", False)),
            "image_id": image_id or None,
        }
    return list(entries.values())

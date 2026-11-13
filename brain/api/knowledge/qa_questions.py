"""Every quick Q&A question in one flat list, for the admin's "所有題目" view.

快速問答平常只能一個分類一個分類看；跨分類的檢查（哪些題沒答案、哪些英文題放錯分類、哪些題不在選單上）
要把題目攤平才看得出來。這裡把問答文件的每一題和選單上的掛載合在一起，一題一列：
題目的身分是「來源文件＋題目文字」，只在選單上、沒有來源文件的題目是「分類＋題目文字」。
掛在多個分類的題目只算一列，分類照樹上的順序列出。只讀，不改任何資料。
"""

from __future__ import annotations

import posixpath
from pathlib import Path
from typing import Any

from knowledge.doc_meta import load_doc_meta, resolve_document_languages
from knowledge.qa_csv import (
    UNTITLED_QUESTION,
    extract_image_id,
    normalize_row_language,
    qa_csv_row_extras,
    unify_newlines,
)
from knowledge.qa_nodes import (
    _load_nodes_data,
    _lock,
    _parse_source_items,
    get_node_tree,
    referenced_source_paths,
)
from knowledge.workspace import resolve_workspace_document


def question_key(text: str) -> str:
    """Compare questions the same way everywhere: line breaks and outer spaces do not count.

    選單上記的題目和檔案裡的題目是分開存的；換行符號不同（例如 Windows 的 \\r\\n）就對不上，
    掛著的題目會被誤算成「不在選單上」。
    """
    return unify_newlines(text or "").strip()


def _source_key(path: str) -> str:
    return posixpath.normpath(path) if path else ""


def _is_manual(path: str) -> bool:
    return Path(path).name.startswith("manual_")


def _categories(tree: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Categories in tree order with their path and whether they show, plus each one's entries."""
    categories: list[dict[str, Any]] = []
    entries: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()

    def walk(node: dict[str, Any], path: list[str], hidden_above: bool, parent_id: str | None) -> None:
        node_id = node["node_id"]
        if node_id in seen:
            return
        seen.add(node_id)
        label = node.get("label") or node_id
        hidden = hidden_above or bool(node.get("hidden"))
        categories.append({
            "node_id": node_id,
            "label": label,
            "path": [*path, label],
            "parent_id": parent_id,
            # 自己或上層被隱藏，前台都看不到。
            "hidden": hidden,
        })
        entries[node_id] = list(node.get("qa_entries", []))
        for child in node.get("children", []):
            walk(child, [*path, label], hidden, node_id)

    for root in tree:
        walk(root, [], False, None)
    return categories, entries


def _qa_document_paths(project_id: str) -> set[str]:
    meta = load_doc_meta(project_id)
    paths = {path for path, value in meta.items() if value.get("source_type") == "qa"}
    return paths | set(referenced_source_paths(project_id))


def _file_rows(source: str, project_id: str) -> list[dict[str, Any]]:
    """The questions of one QA document, last row winning for a repeated question."""
    try:
        doc_path = resolve_workspace_document(source, project_id)
    except ValueError:
        return []
    if not doc_path.is_file():
        return []
    try:
        items = _parse_source_items(source, project_id)
        labels = qa_csv_row_extras(doc_path.read_bytes()) if source.lower().endswith(".csv") else {}
    except (OSError, UnicodeDecodeError, ValueError):
        return []
    rows: dict[str, dict[str, Any]] = {}
    row_labels = {question_key(question): extra.get("language", "") for question, extra in labels.items()}
    for item in items:
        question = item["q"].strip()
        if not question or question == UNTITLED_QUESTION:
            continue
        rows[question_key(question)] = {
            "question": question,
            "answer": (item.get("a") or "").strip(),
            "image": extract_image_id(item.get("img") or ""),
            "url": (item.get("url") or "").strip(),
            "hidden_in_file": bool(item.get("hidden", False)),
            "row_language": normalize_row_language(row_labels.get(question_key(question), "")),
        }
    return list(rows.values())


def list_all_questions(project_id: str = "default") -> dict[str, Any]:
    """Every question with its answer, language, source, categories and states."""
    tree = get_node_tree(project_id)
    categories, entries_by_node = _categories(tree)
    with _lock:
        detached_raw = _load_nodes_data(project_id).get("detached", {})
    detached = {
        _source_key(source): {question_key(question) for question in questions}
        for source, questions in detached_raw.items()
    }

    # 每個（來源、題目）掛在哪些分類，照樹上的順序。
    mounts: dict[tuple[str, str], list[str]] = {}
    menu_only: list[dict[str, Any]] = []
    # 清單照樹上第一次出現的位置排，和工作人員在樹上看到的順序一樣；不在選單上的排最後。
    position: dict[str, int] = {}
    for category in categories:
        for entry in entries_by_node.get(category["node_id"], []):
            question = entry.get("question") or ""
            source = _source_key(entry.get("source_path") or "")
            id_key = f"{source}::{question_key(question)}" if source else f"menu::{category['node_id']}::{question_key(question)}"
            position.setdefault(id_key, len(position))
            if not source:
                menu_only.append({"node_id": category["node_id"], "question": question})
                continue
            node_ids = mounts.setdefault((source, question_key(question)), [])
            if category["node_id"] not in node_ids:
                node_ids.append(category["node_id"])

    hidden_category = {category["node_id"]: category["hidden"] for category in categories}

    def category_hidden(node_ids: list[str]) -> bool:
        # 掛在多個分類時，只要有一個看得到，訪客就點得到。
        return bool(node_ids) and all(hidden_category.get(node_id, False) for node_id in node_ids)

    meta = load_doc_meta(project_id)
    sources = sorted(_qa_document_paths(project_id))
    languages = resolve_document_languages(sources, project_id) if sources else {}
    questions: list[dict[str, Any]] = []
    listed: set[tuple[str, str]] = set()
    for source in sources:
        key_source = _source_key(source)
        manual = _is_manual(source)
        for row in _file_rows(source, project_id):
            key = (key_source, question_key(row["question"]))
            listed.add(key)
            node_ids = mounts.get(key, [])
            off_menu = None
            if not node_ids:
                off_menu = "detached" if key[1] in detached.get(key_source, set()) else "never"
            questions.append({
                "id": f"{key_source}::{key[1]}",
                "question": row["question"],
                "answer": row["answer"],
                "image": row["image"],
                "url": row["url"],
                "language": row["row_language"] or languages.get(source) or None,
                "source": {
                    "kind": "manual" if manual else "file",
                    "path": source,
                    "label": "自己輸入" if manual else Path(source).name,
                },
                "category_ids": node_ids,
                "category_hidden": category_hidden(node_ids),
                "hidden_in_file": row["hidden_in_file"],
                "off_menu": off_menu,
                "no_answer": not row["answer"],
                "document_enabled": meta.get(source, {}).get("enabled", True) is not False,
            })

    # 掛在選單上、但文件裡已經找不到的題目：照樣列出，答案是空的。
    for (source, key_question), node_ids in mounts.items():
        if (source, key_question) in listed:
            continue
        questions.append({
            "id": f"{source}::{key_question}",
            "question": key_question,
            "answer": "",
            "image": "",
            "url": "",
            "language": languages.get(source) or None,
            "source": {
                "kind": "manual" if _is_manual(source) else "file",
                "path": source,
                "label": "自己輸入" if _is_manual(source) else Path(source).name,
            },
            "category_ids": node_ids,
            "category_hidden": category_hidden(node_ids),
            "hidden_in_file": False,
            "off_menu": None,
            "no_answer": True,
            "document_enabled": meta.get(source, {}).get("enabled", True) is not False,
        })

    seen_menu_only: set[tuple[str, str]] = set()
    for item in menu_only:
        key = (item["node_id"], question_key(item["question"]))
        if key in seen_menu_only:
            continue
        seen_menu_only.add(key)
        questions.append({
            "id": f"menu::{item['node_id']}::{key[1]}",
            "question": item["question"],
            "answer": "",
            "image": "",
            "url": "",
            "language": None,
            "source": {"kind": "menu_only", "path": "", "label": "只在選單上"},
            "category_ids": [item["node_id"]],
            "category_hidden": category_hidden([item["node_id"]]),
            "hidden_in_file": False,
            "off_menu": None,
            # 只在選單上的題目本來就沒有答案：點了是把題目交給 AI 回答，不算缺答案。
            "no_answer": False,
            "document_enabled": True,
        })

    unplaced = len(position)
    questions = [
        item for _, item in sorted(
            enumerate(questions), key=lambda pair: (position.get(pair[1]["id"], unplaced), pair[0]),
        )
    ]
    return {"categories": categories, "questions": questions}

"""Read-only preview for staged raw uploads before committing them to the knowledge base."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from knowledge.converters import SUPPORTED_SUFFIXES, qa_table_csv_bytes
from knowledge.doc_meta import LANGUAGE_SOURCE_MANUAL, load_doc_meta
from knowledge.qa_csv import UNTITLED_QUESTION
from knowledge.qa_images import resolve_qa_image_path
from knowledge.qa_import_placement import (
    build_node_tree,
    place_entries_by_path,
    referencing_nodes,
    source_node_can_refill,
    source_node_id,
)
from knowledge.qa_import_review import (
    claimed_target_error,
    missing_language_category,
    new_table_duplicate_error,
    prepare_qa_document,
    prepare_qa_table,
    qa_table_notes,
    question_paths,
)
from knowledge.qa_merged import MergedSaveError, compare_reupload, reupload_format_error
from knowledge.qa_nodes import find_language_category, is_qa_document, source_placement_snapshot
from knowledge.raw_import import list_raw_files, normalize_raw_paths, qa_table_target
from knowledge.workspace import (
    ensure_workspace_scaffold,
    resolve_workspace_document,
    without_workspace_scaffold,
)
from safety.vendor_access import vendor_workspace_path, visible_workspace_path

_LANGUAGE_SAMPLE_CHARS = 20000


def _preview_document_language(
    target: str,
    content: str,
    project_id: str,
) -> str:
    from memory.language_detect import detect_document_language

    meta_entry = load_doc_meta(project_id).get(target, {})
    if meta_entry.get("language_source") == LANGUAGE_SOURCE_MANUAL and meta_entry.get("language"):
        return str(meta_entry["language"])
    sample = content[:_LANGUAGE_SAMPLE_CHARS]
    return detect_document_language(sample)


def _node_paths_by_id(nodes: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    paths: dict[str, list[str]] = {}

    def walk(nodes: list[dict[str, Any]], prefix: list[str], seen: set[str]) -> None:
        for node in nodes:
            node_id = node["node_id"]
            if node_id in seen:
                continue
            label = str(node.get("label") or node_id)
            current = [*prefix, label]
            paths.setdefault(node_id, current)
            walk(node.get("children", []), current, seen | {node_id})

    walk(build_node_tree(nodes), [], set())
    return paths


def _preview_placements(
    target: str,
    stem: str,
    questions: list[str],
    extras: dict[str, dict[str, Any]],
    languages: dict[str, str],
    doc_language: str,
    *,
    mixed: bool,
    existing_qa: bool,
    project_id: str,
) -> tuple[dict[str, list[str] | None], dict[str, int]]:
    nodes, detached = source_placement_snapshot(target, project_id)
    referenced = bool(referencing_nodes(nodes, target))
    emptied_id = source_node_id(stem)
    can_refill = source_node_can_refill(nodes, emptied_id)
    by_path = mixed or any(row["path"] or row["levels"] for row in extras.values())

    if not referenced and (existing_qa or (can_refill and not by_path)):
        refill_path = _node_paths_by_id(nodes).get(emptied_id) if can_refill else None
        return dict.fromkeys(questions, refill_path), {}

    category = find_language_category(doc_language, project_id)
    missing_categories: dict[str, int] = {}
    if by_path:
        paths, missing_categories, _ = question_paths(
            extras, languages if mixed else {}, category, stem, project_id,
            report_missing=not existing_qa,
        )
        place_entries_by_path(
            nodes, target,
            [{"question": question, "source_path": target} for question in questions],
            paths, detached,
        )
    if by_path or referenced:
        node_paths = _node_paths_by_id(nodes)
        placements: dict[str, list[str] | None] = dict.fromkeys(questions)
        for node_id, path in node_paths.items():
            for entry in nodes[node_id].get("qa_entries", []):
                question = entry.get("question")
                if entry.get("source_path") == target and question in placements and placements[question] is None:
                    placements[question] = path
        if referenced:
            primary_id = referencing_nodes(nodes, target)[0]
            primary = nodes[primary_id]
            occupied = {
                entry["question"] for entry in primary.get("qa_entries", [])
                if entry.get("source_path") and entry["source_path"] != target
            }
            for question in questions:
                if placements[question] is None and question not in detached and question not in occupied:
                    placements[question] = node_paths.get(primary_id)
        return placements, missing_categories

    missing_categories = missing_language_category(doc_language, category, project_id)
    default_path = [*([str(nodes[category].get("label", ""))] if category in nodes else []), stem]
    return dict.fromkeys(questions, default_path), missing_categories


def _preview_raw_file(
    relative: str,
    project_id: str,
    *,
    claimed_targets: dict[str, str],
    vendor: bool = False,
) -> dict[str, Any]:
    root = ensure_workspace_scaffold(project_id)
    src = root / "raw" / relative
    if vendor:
        vendor_workspace_path(project_id, f"raw/{relative}", "raw")
        vendor_workspace_path(project_id, f"archive/originals/{relative}", "archive")
    if not src.is_file() or src.suffix.lower() not in SUPPORTED_SUFFIXES:
        return {"kind": "document"}

    origin_bytes = src.read_bytes()
    qa_csv = qa_table_csv_bytes(src, origin_bytes)
    if qa_csv is None:
        return {"kind": "document"}

    table = prepare_qa_table(src, origin_bytes, qa_csv, project_id)
    qa_csv, extras, languages = table.qa_csv, table.extras, table.languages
    notes: list[str] = []
    target_rel = qa_table_target(
        src.name,
        project_id,
        keep_csv=any(row["language"] for row in extras.values()),
    )
    target = target_rel.as_posix()
    if vendor:
        vendor_workspace_path(project_id, target, "knowledge")
    mixed = bool(table.split_for(target_rel, project_id, notes))
    dest = resolve_workspace_document(target, project_id)
    existing = dest.exists() and is_qa_document(target, project_id)

    draft = prepare_qa_document(qa_csv, target_rel)
    entries = draft.entries
    errors = (
        [claimed_target_error(claimed_targets[target])]
        if target in claimed_targets else draft.errors
    )
    doc_language = _preview_document_language(target, draft.content or "", project_id)

    comparison = None
    if existing:
        try:
            comparison = compare_reupload(target, entries, project_id)
            if not errors and (reason := reupload_format_error(comparison)):
                errors.append(reason)
        except MergedSaveError as exc:
            if not errors:
                errors.append(exc.detail)
    elif not errors and (reason := new_table_duplicate_error(entries)):
        errors.append(reason)

    if comparison is not None:
        question_names = [
            item.question
            for item in comparison.questions
            if item.question and item.question != UNTITLED_QUESTION
        ]
    else:
        question_names = list(dict.fromkeys(
            q
            for entry in entries
            if (q := entry["q"].strip()) and q != UNTITLED_QUESTION
        ))

    placements, missing_categories = _preview_placements(
        target,
        target_rel.stem,
        question_names,
        extras,
        languages,
        doc_language,
        mixed=mixed,
        existing_qa=existing,
        project_id=project_id,
    )

    questions: list[dict[str, Any]] = []
    if comparison is not None:
        for item in comparison.questions:
            if not item.question or item.question == UNTITLED_QUESTION:
                continue
            q_info: dict[str, Any] = {
                "question": item.question,
                "status": item.status,
                "placement": placements.get(item.question),
                "language": languages.get(item.question) or doc_language,
            }
            if item.status == "conflict" and item.old is not None:
                q_info["old"] = {
                    "answer": item.old["a"],
                    "image": item.old["img"],
                    "url": item.old["url"],
                }
                q_info["new"] = {
                    "answer": item.new["a"],
                    "image": item.new["img"],
                    "url": item.new["url"],
                }
            questions.append(q_info)
    else:
        for q in question_names:
            questions.append({
                "question": q,
                "status": "new",
                "placement": placements.get(q),
                "language": languages.get(q) or doc_language,
            })

    image_exists = lambda image_id: resolve_qa_image_path(image_id, project_id) is not None
    missing_by_image: dict[str, list[str]] = {}
    for entry in entries:
        img = entry["img"]
        q = entry["q"].strip()
        if img and not image_exists(img):
            used_by = missing_by_image.setdefault(img, [])
            if q and q != UNTITLED_QUESTION and q not in used_by:
                used_by.append(q)
    missing_images = [
        {"image": img, "questions": used_by}
        for img, used_by in missing_by_image.items()
    ]

    notes += qa_table_notes(
        ignored=table.ignored,
        entries=entries,
        extras=extras,
        missing_categories=missing_categories,
        stem=target_rel.stem,
        image_exists=image_exists,
    )

    question_counts = Counter(
        q for entry in entries if (q := entry["q"].strip()) and q != UNTITLED_QUESTION
    )
    return {
        "kind": "qa",
        "target": target,
        "existing": existing,
        "errors": errors,
        "duplicate_rows": sum(count for count in question_counts.values() if count > 1),
        "questions": questions,
        "missing_images": missing_images,
        "notes": notes,
    }


@without_workspace_scaffold()
def preview_raw_documents(
    project_id: str = "default",
    *,
    paths: Iterable[str] | None = None,
    vendor: bool = False,
) -> dict[str, Any]:
    """Preview staged raw/ files without writing files, modifying nodes, or moving raw uploads."""
    relative_paths = (
        list_raw_files(project_id) if paths is None else normalize_raw_paths(paths, project_id)
    )
    if vendor:
        for path in [] if paths is None else relative_paths:
            vendor_workspace_path(project_id, f"raw/{path}", "raw")
        relative_paths = [
            path
            for path in relative_paths
            if visible_workspace_path(project_id, f"raw/{path}", "raw")
        ]

    claimed_targets: dict[str, str] = {}
    files: dict[str, dict[str, Any]] = {}
    for relative in relative_paths:
        preview = _preview_raw_file(
            relative,
            project_id,
            claimed_targets=claimed_targets,
            vendor=vendor,
        )
        files[relative] = preview
        if preview.get("target") and not preview["errors"]:
            claimed_targets.setdefault(preview["target"], relative)

    return {"files": files}

"""Stage and import raw uploads into the workspace knowledge base."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from core.gemini_credentials import project_model_entry
from knowledge.doc_meta import touch_document_meta, upsert_document_meta
from knowledge.knowledge_admin import qa_document_lock
from knowledge.qa_csv import replace_qa_csv_images
from knowledge.workspace import (
    ensure_workspace_scaffold,
    resolve_workspace_document,
    write_text_atomic,
)
from safety.upload_paths import raw_relative_path
from safety.vendor_access import vendor_workspace_path

logger = logging.getLogger("brain.knowledge.admin")


def _archive_original(src: Path, rel_in_raw: Path, root: Path) -> str:
    """Move the committed original file into archive/originals/, returning its relative path."""
    dest = root / "archive" / "originals" / rel_in_raw
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        dest = dest.with_name(f"{dest.stem}-{stamp}{dest.suffix}")
    src.replace(dest)
    return dest.relative_to(root).as_posix()


def list_raw_files(project_id: str = "default") -> list[str]:
    """List all staged files under raw/, relative to raw root."""
    root = ensure_workspace_scaffold(project_id)
    raw_root = root / "raw"
    if not raw_root.exists():
        return []
    return sorted(
        p.relative_to(raw_root).as_posix()
        for p in raw_root.rglob("*")
        if p.is_file()
    )


def normalize_raw_paths(paths: Iterable[str], project_id: str = "default") -> list[str]:
    """Return client-supplied paths relative to raw/, deduplicated, rejecting traversal."""
    raw_root = ensure_workspace_scaffold(project_id) / "raw"
    return list(dict.fromkeys(raw_relative_path(path, raw_root) for path in paths))


def list_pending_raw_files(project_id: str = "default") -> list[dict[str, Any]]:
    """Describe the files waiting under raw/, for the admin's pending list."""
    raw_root = ensure_workspace_scaffold(project_id) / "raw"
    files: list[dict[str, Any]] = []
    for relative in list_raw_files(project_id):
        try:
            stat = (raw_root / relative).stat()
        except FileNotFoundError:
            continue
        files.append({
            "path": relative,
            "size": stat.st_size,
            "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    return files


def delete_raw_file(relative_path: str, project_id: str = "default") -> None:
    """Remove one waiting file; ``relative_path`` comes from :func:`normalize_raw_paths`."""
    path = ensure_workspace_scaffold(project_id) / "raw" / relative_path
    if not path.is_file():
        raise FileNotFoundError("找不到指定檔案")
    path.unlink()


class _ImportRefused(Exception):
    """This file cannot be imported; the message is shown to staff as written."""


_REASON_MISSING = "找不到這個檔案，可能已經被移除"
_REASON_NO_TEXT = "讀不到文字內容，可能是掃描檔或檔案損毀"
_REASON_TARGET_IS_QA = "快速問答已經有同名的問答文件，請改檔名後再上傳"
_REASON_NOT_UTF8 = "這個檔案不是 UTF-8 編碼，請另存成 UTF-8 後再上傳"
_REASON_FAILED = "處理這個檔案時發生錯誤，可以再試一次；一直失敗請找管理員"
_PLAIN_TEXT_SUFFIXES = frozenset({".md", ".txt", ".csv"})


def _no_text_reason(src: Path, origin_bytes: bytes) -> str:
    if src.suffix.lower() in _PLAIN_TEXT_SUFFIXES:
        try:
            origin_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            return _REASON_NOT_UTF8
    return _REASON_NO_TEXT


def qa_table_target(filename: str, project_id: str, keep_csv: bool = False) -> Path:
    """Where an imported QA table is stored: ``knowledge/qa/<name>.md``.

    拖進樹的 CSV 文件不會轉成 .md；同名的已經掛在樹上時要更新它，不能另開一份多一個分類。
    每題標了語言的表（``keep_csv``）也留 CSV，Markdown 放不下語言欄。
    """
    from knowledge.qa_nodes import is_qa_document

    markdown = (Path("knowledge/qa") / filename).with_suffix(".md")
    existing_csv = markdown.with_suffix(".csv")
    if not is_qa_document(markdown.as_posix(), project_id) and (
        keep_csv or is_qa_document(existing_csv.as_posix(), project_id)
    ):
        return existing_csv
    return markdown


def _qa_node_summary(target: str, project_id: str) -> dict[str, Any]:
    """The category holding ``target``, for the per-file result shown in the admin."""
    from knowledge.qa_nodes import list_nodes

    nodes = list_nodes(project_id)
    counts = {
        node_id: sum(entry.get("source_path") == target for entry in node.get("qa_entries", []))
        for node_id, node in nodes.items()
    }
    node_id = max(counts, key=counts.get, default=None)
    if node_id is None or not counts[node_id]:
        return {}
    node = nodes[node_id]
    category_count = sum(1 for count in counts.values() if count)
    summary = {
        "qa_node_id": node_id,
        "qa_node_label": node.get("label", ""),
        "question_count": sum(counts.values()),
        **({"qa_category_count": category_count} if category_count > 1 else {}),
    }
    parent = next((nodes[pid] for pid in node.get("parent_ids", []) if pid in nodes), None)
    return {**summary, "qa_parent_label": parent.get("label", "")} if parent else summary


def _commit_raw_file(
    relative: str,
    project_id: str,
    *,
    normalize: bool,
    claimed_targets: dict[str, str],
    report: Callable[[str], None],
    vendor: bool = False,
    file_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Import one raw/ file and describe the outcome.

    Raises :class:`_ImportRefused` with the reason when the file cannot be imported.
    """
    from knowledge.converters import (
        SUPPORTED_SUFFIXES,
        convert_to_text,
        qa_table_csv_bytes,
    )
    from knowledge.doc_meta import resolve_document_languages
    from knowledge.normalizer import normalize_to_markdown
    from knowledge.qa_images import resolve_qa_image_path
    from knowledge.qa_import_review import (
        claimed_target_error,
        is_mixed,
        language_counts,
        missing_language_category,
        new_table_duplicate_error,
        not_a_qa_table_note,
        prepare_qa_document,
        prepare_qa_table,
        qa_table_notes,
        question_paths,
        row_languages,
    )
    from knowledge.qa_merged import MergedSaveError, merge_reupload
    from knowledge.qa_nodes import (
        create_node_for_source,
        find_language_category,
        is_qa_document,
        is_source_referenced,
        place_questions_by_path,
        refill_emptied_node,
        sync_entries_for_source,
    )

    root = ensure_workspace_scaffold(project_id)
    src = root / "raw" / relative
    if vendor:
        vendor_workspace_path(project_id, f"raw/{relative}", "raw")
        vendor_workspace_path(project_id, f"archive/originals/{relative}", "archive")
    if not src.is_file():
        raise _ImportRefused(_REASON_MISSING)
    if src.suffix.lower() not in SUPPORTED_SUFFIXES:
        allowed = "、".join(sorted(SUPPORTED_SUFFIXES))
        raise _ImportRefused(f"這個格式不支援，請改用 {allowed}")

    report("normalizing")

    origin_bytes = src.read_bytes()
    qa_csv = qa_table_csv_bytes(src, origin_bytes)
    is_qa = qa_csv is not None
    table = prepare_qa_table(src, origin_bytes, qa_csv, project_id) if qa_csv is not None else None
    qa_csv, extras, languages = (table.qa_csv, table.extras, table.languages) if table else (None, {}, {})
    conflict_decisions: dict[str, str] = dict((file_decision or {}).get("conflicts") or {})
    image_map: dict[str, str] = {
        str(k).strip(): str(v).strip()
        for k, v in ((file_decision or {}).get("images") or {}).items()
        if str(k).strip()
    }
    if is_qa and image_map:
        for new_image_id in image_map.values():
            if not new_image_id or resolve_qa_image_path(new_image_id, project_id) is None:
                raise _ImportRefused(f"補傳的圖片「{new_image_id}」不存在，這份檔案沒有匯入")
        qa_csv = replace_qa_csv_images(qa_csv, image_map)
    notes: list[str] = []
    missing_categories: dict[str, int] = {}
    by_language = False
    target_rel = (
        qa_table_target(
            src.name, project_id, keep_csv=any(row["language"] for row in extras.values()),
        )
        if is_qa
        else (Path("knowledge") / relative).with_suffix(".md")
    )
    target = target_rel.as_posix()
    mixed = bool(table and table.split_for(target_rel, project_id, notes))
    if target in claimed_targets:
        # 同名不同副檔名（a.csv、a.xlsx）或不同資料夾的問答表會存成同一份，後面的會蓋掉前面的。
        raise _ImportRefused(claimed_target_error(claimed_targets[target]))

    entries: list[dict[str, Any]] = []
    if qa_csv is not None:
        draft = prepare_qa_document(qa_csv, target_rel)
        if draft.errors:
            raise _ImportRefused("\n".join(draft.errors))
        content, entries = draft.content, draft.entries
    else:
        text = convert_to_text(src)
        if not text:
            raise _ImportRefused(_no_text_reason(src, origin_bytes))
        content = normalize_to_markdown(text) if normalize else text
        if not content.strip():
            raise _ImportRefused(_REASON_NO_TEXT)

    if vendor:
        vendor_workspace_path(project_id, target, "knowledge")
    dest = resolve_workspace_document(target, project_id)
    origin_hash = hashlib.sha256(origin_bytes).hexdigest()
    both_questions: list[str] = []
    later_items: list[dict[str, str]] = []
    archived_rel: str | None = None
    # 節點寫在中繼資料之前：source_type 一標成 qa，輪詢問答樹時就會把還沒節點的文件自動收養，
    # 接著這裡又建一次，就多出一個分類。原檔最後才搬走，中途失敗都還能重跑。
    with qa_document_lock:
        updated = dest.exists()
        referenced = is_source_referenced(target, project_id)
        if not is_qa and is_qa_document(target, project_id):
            raise _ImportRefused(_REASON_TARGET_IS_QA)
        # 同名的問答文件已經存在時是合併，不是取代：後台新增的題目和掛在別的分類的題目都不能消失。
        merge_counts: dict[str, int] = {}
        existing_qa = is_qa and updated and is_qa_document(target, project_id)
        if existing_qa:
            try:
                merged = merge_reupload(
                    target,
                    entries,
                    extras,
                    project_id,
                    conflict_decisions=conflict_decisions,
                    image_map=image_map,
                )
            except MergedSaveError as exc:
                raise _ImportRefused(exc.detail) from exc
            content = merged.content
            merge_counts = {"added": merged.added, "kept": merged.kept}
            both_questions = merged.both
            later_items = merged.later
            if both_questions:
                languages = row_languages(extras)
        elif is_qa and (reason := new_table_duplicate_error(entries)):
            raise _ImportRefused(reason)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if content is not None:
            write_text_atomic(dest, content)
            touch_document_meta(target, project_id)
        language = resolve_document_languages([target], project_id)[target]
        name_clashes: list[str] = []
        if is_qa and existing_qa and not referenced:
            # 分類刪掉的文件只更新內容，不回選單，表裡有 path 也一樣；分類還在但題目都拿掉了才接回去。
            refill_emptied_node(target, target_rel.stem, project_id)
        elif is_qa:
            category = find_language_category(language, project_id)
            if mixed or any(row["path"] or row["levels"] for row in extras.values()):
                # 同一份表裡沒填 path 與 levels 的題目，不論第一次匯入或重傳，都放以檔名命名的分類；
                # 混了語言的表，每題放進自己語言的分類。語言分類不自動建立，沒有就放最上層。
                paths, missing_categories, by_language = question_paths(
                    extras, languages if mixed else {}, category, target_rel.stem, project_id,
                    report_missing=not existing_qa,
                )
                name_clashes = place_questions_by_path(target, paths, project_id)
                if referenced:
                    sync_entries_for_source(target, project_id)
            elif referenced:
                sync_entries_for_source(target, project_id)
            elif not refill_emptied_node(target, target_rel.stem, project_id):
                missing_categories = missing_language_category(language, category, project_id)
                create_node_for_source(
                    target,
                    target_rel.stem,
                    project_id,
                    parent_ids=[category] if category else None,
                )
        upsert_document_meta(target, project_id, source_type="qa" if is_qa else "upload")
        # AI 整理要幾分鐘，這段時間可能又傳了新版；留在 raw/ 等下一批，不能當成這一版搬走。
        if hashlib.sha256(src.read_bytes()).hexdigest() == origin_hash:
            archived_rel = _archive_original(src, Path(relative), root)
            upsert_document_meta(
                target, project_id, origin_path=archived_rel, origin_hash=origin_hash,
            )

    if qa_csv is not None:
        notes += qa_table_notes(
            ignored=table.ignored if table else [],
            entries=entries,
            extras=extras,
            missing_categories=missing_categories,
            stem=target_rel.stem,
            image_exists=lambda image_id: resolve_qa_image_path(image_id, project_id) is not None,
        )
    else:
        notes += [note] if (note := not_a_qa_table_note(src)) else []
    result = {
        "target": target,
        "kind": "qa" if is_qa else "document",
        "language": language,
        "updated": updated,
        **merge_counts,
        **({"both": both_questions} if both_questions else {}),
        **(
            {
                "later": later_items,
                **({"origin_path": archived_rel} if archived_rel else {}),
            }
            if later_items
            else {}
        ),
        **({"name_clashes": name_clashes} if name_clashes else {}),
        **({"languages": language_counts(languages)} if by_language and is_mixed(languages) else {}),
        **({"notes": notes} if notes else {}),
    }
    return {**result, **_qa_node_summary(target, project_id)} if is_qa else result


def _normalize_decisions(
    decisions: dict[str, Any] | None,
    project_id: str,
) -> dict[str, dict[str, Any]]:
    if not decisions:
        return {}
    raw_root = ensure_workspace_scaffold(project_id) / "raw"
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, item in decisions.items():
        value = item.model_dump() if hasattr(item, "model_dump") else dict(item or {})
        try:
            rel = raw_relative_path(raw_key, raw_root)
        except ValueError:
            rel = raw_key
        normalized[rel] = value
    return normalized


@project_model_entry("knowledge")
def commit_raw_documents(
    project_id: str = "default",
    on_progress: Callable[[str, str], None] | None = None,
    *,
    paths: Iterable[str] | None = None,
    normalize: bool = True,
    on_result: Callable[[str, dict[str, Any]], None] | None = None,
    on_skip: Callable[[str, str], None] | None = None,
    vendor: bool = False,
    decisions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Promote staged files from raw/ into knowledge/ (the 'commit' step).

    raw/ is a staging area (uploads land there un-indexed). Each file becomes a
    ``.md`` under knowledge/ preserving its sub-path: QA tables (CSV, or Excel whose
    every non-empty sheet has question and answer columns) become QA documents under
    ``knowledge/qa/`` without any LLM step and join the quick Q&A tree; anything else
    is converted to text and LLM-cleaned, unless ``normalize`` is false. A QA source
    that already has a node updates that node's questions, keeping its name and place;
    a new one goes under the first-level category of its language when there is one.
    The caller then triggers reindex + graph rebuild.

    ``paths`` limits the run to those files (relative to raw/, see
    :func:`normalize_raw_paths`); ``None`` means everything in raw/. One file failing
    never stops the others: it stays in raw/ and its reason lands in ``skip_reasons``.
    """
    relative_paths = (
        list_raw_files(project_id) if paths is None else normalize_raw_paths(paths, project_id)
    )
    decisions_by_path = _normalize_decisions(decisions, project_id)

    def _report(path: str, state: str) -> None:
        if on_progress:
            on_progress(path, state)

    committed: list[str] = []
    skipped: list[str] = []
    results: dict[str, dict[str, Any]] = {}
    skip_reasons: dict[str, str] = {}
    claimed_targets: dict[str, str] = {}
    for relative in relative_paths:
        file_decision = decisions_by_path.get(relative)
        try:
            result = _commit_raw_file(
                relative,
                project_id,
                normalize=normalize,
                claimed_targets=claimed_targets,
                report=partial(_report, relative),
                **({"vendor": True} if vendor else {}),
                **({"file_decision": file_decision} if file_decision else {}),
            )
        except _ImportRefused as refused:
            reason = str(refused)
        except Exception:  # noqa: BLE001 - one bad file must not stop the batch
            logger.exception("raw commit failed project=%s path=%s", project_id, relative)
            reason = _REASON_FAILED
        else:
            claimed_targets[result["target"]] = relative
            committed.append(result["target"])
            results[relative] = result
            if on_result:
                on_result(relative, result)
            _report(relative, "committed")
            continue
        skipped.append(relative)
        skip_reasons[relative] = reason
        if on_skip:
            on_skip(relative, reason)
        _report(relative, "skipped")

    return {
        "committed": committed,
        "skipped": skipped,
        "results": results,
        "skip_reasons": skip_reasons,
    }

"""Workspace document management for the admin console."""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from core.gemini_credentials import project_model_entry
from knowledge.doc_meta import (
    delete_document_meta,
    get_document_meta,
    move_document_meta,
    touch_document_meta,
    upsert_document_meta,
)
from knowledge.indexer import fingerprint_document, load_index_state
from knowledge.qa_csv import (
    UNTITLED_QUESTION,
    convert_csv_to_qa_markdown,
    normalize_qa_csv_rows,
    parse_qa_csv,
    parse_qa_markdown,
    qa_entry_values,
)
from knowledge.workspace import (
    ensure_workspace_scaffold,
    get_core_documents,
    is_indexable_document,
    iter_knowledge_documents,
    iter_workspace_documents,
    resolve_workspace_artifact,
    resolve_workspace_document,
    write_text_atomic,
)
from personas.personas import is_persona_core_relative_path

logger = logging.getLogger("brain.knowledge.admin")

# 問答文件會被整份改寫：拖曳併入（讀目標、寫入、更新節點、刪來源）和同名重傳（寫入、更新節點）。
# 兩邊同時做的話，一邊的題目會被另一邊蓋掉，而來源檔已經刪掉或搬走。
qa_document_lock = threading.Lock()


def _sanitize_relative_subpath(raw: str) -> Path:
    """Normalize a client-supplied relative path, rejecting traversal.

    Strips leading slashes and rejects any segment that is empty, ``.`` or
    ``..`` so callers cannot escape the intended ``target_dir``.
    """
    cleaned = raw.strip().lstrip("/\\")
    if not cleaned:
        raise ValueError("relative_path 不可為空")
    parts = Path(cleaned).parts
    for part in parts:
        if part in ("", ".", "..") or part.startswith(("/", "\\")):
            raise ValueError("relative_path 不允許 .. 或絕對路徑片段")
    return Path(*parts)


def list_knowledge_base_directories(project_id: str = "default") -> list[str]:
    """Return subdirectory paths under knowledge/ that hold documents.

    系統自己用的資料夾不列：.qa_images 放問答圖片（圖片不是文件，樹上看起來是空的，
    容易被當成沒用而刪掉），graphify-out 是舊版留下的圖譜快取。
    """
    root = ensure_workspace_scaffold(project_id)
    knowledge_dir = root / "knowledge"
    return sorted(
        p.relative_to(root).as_posix()
        for p in knowledge_dir.rglob("*")
        if p.is_dir() and not any(
            part == "graphify-out" or part.startswith(".")
            for part in p.relative_to(knowledge_dir).parts
        )
    )


def _list_document_summaries(paths: Iterable[Path], project_id: str) -> list[dict[str, Any]]:
    """Build summaries with per-list shared index/QA-reference state."""
    from knowledge.doc_meta import load_doc_meta
    from knowledge.qa_nodes import referenced_source_paths

    root = ensure_workspace_scaffold(project_id)
    core_docs = get_core_documents(project_id)
    core_paths = {core_path.relative_to(root).as_posix() for core_path in core_docs.values()}
    index_state = load_index_state(project_id)
    qa_paths = referenced_source_paths(project_id)
    doc_meta = load_doc_meta(project_id)
    return [
        _build_document_summary(
            path,
            project_id,
            root=root,
            core_paths=core_paths,
            index_state=index_state,
            qa_referenced_paths=qa_paths,
            doc_meta=doc_meta,
        )
        for path in paths
    ]


def list_knowledge_base_documents(project_id: str = "default") -> list[dict[str, Any]]:
    """Return documents under the workspace knowledge/ directory."""
    from knowledge.doc_meta import resolve_document_languages

    paths = list(iter_knowledge_documents(project_id))
    root = ensure_workspace_scaffold(project_id)
    # 列表要顯示每份文件的語言；還沒判斷過的在這裡判斷並存起來。
    resolve_document_languages(
        (path.relative_to(root).as_posix() for path in paths if is_indexable_document(path, project_id)),
        project_id,
    )
    return _list_document_summaries(paths, project_id)


def list_workspace_documents(project_id: str = "default") -> list[dict[str, Any]]:
    """Return editable documents under the workspace."""
    ensure_workspace_scaffold(project_id)
    return _list_document_summaries(iter_workspace_documents(project_id), project_id)


def read_workspace_document(relative_path: str, project_id: str = "default") -> dict[str, Any]:
    """Read a document from the workspace."""
    path = resolve_workspace_document(relative_path, project_id)
    content = path.read_text(encoding="utf-8-sig")
    summary = _build_document_summary(path, project_id, content=content)
    summary["content"] = content
    return summary


def save_workspace_document(relative_path: str, content: str, project_id: str = "default") -> dict[str, Any]:
    """Create or overwrite a text document in the workspace."""
    path = resolve_workspace_document(relative_path, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, content)
    touch_document_meta(path.relative_to(ensure_workspace_scaffold(project_id)).as_posix(), project_id)
    return _build_document_summary(path, project_id)


def _write_normalization_backup(
    relative_path: str,
    content: str,
    project_id: str,
) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_base = (Path(".normalization-backups") / relative_path).as_posix()
    backup_rel = f"{backup_base}.{timestamp}.bak"
    backup_path = resolve_workspace_artifact(backup_rel, project_id)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(content, encoding="utf-8")
    return backup_rel


@project_model_entry("knowledge")
def preview_workspace_document_normalization(
    relative_path: str,
    project_id: str = "default",
) -> dict[str, Any]:
    from knowledge.normalizer import normalize_to_markdown

    path = resolve_workspace_document(relative_path, project_id)
    if not path.exists():
        raise FileNotFoundError("找不到指定文件")

    original = path.read_text(encoding="utf-8-sig")
    cleaned = normalize_to_markdown(original, strict=True)
    if not cleaned:
        raise ValueError("整理結果為空，已保留原文件")

    workspace_relative = path.relative_to(
        ensure_workspace_scaffold(project_id)
    ).as_posix()
    return {
        "path": workspace_relative,
        "title": path.stem,
        "extension": path.suffix.lower(),
        "content": cleaned,
        "size": len(cleaned.encode("utf-8")),
        "preview": " ".join(cleaned.split())[:140],
    }


def apply_workspace_document_normalization(
    relative_path: str,
    content: str,
    project_id: str = "default",
) -> dict[str, Any]:
    path = resolve_workspace_document(relative_path, project_id)
    if not path.exists():
        raise FileNotFoundError("找不到指定文件")

    cleaned = content.strip()
    if not cleaned:
        raise ValueError("整理結果為空，已保留原文件")

    workspace_relative = path.relative_to(
        ensure_workspace_scaffold(project_id)
    ).as_posix()
    original = path.read_text(encoding="utf-8-sig")
    backup_path = _write_normalization_backup(workspace_relative, original, project_id)
    path.write_text(cleaned, encoding="utf-8")
    touch_document_meta(workspace_relative, project_id)
    summary = _build_document_summary(path, project_id, content=cleaned)
    summary["backup_path"] = backup_path
    return summary


@project_model_entry("knowledge")
def renormalize_workspace_document(relative_path: str, project_id: str = "default") -> dict[str, Any]:
    """Re-run LLM normalization over an existing knowledge/ document, in place.

    For documents that were committed before the normalization pipeline existed
    (e.g. a raw OCR dump). Reads the current file, cleans it into tidy Markdown,
    and overwrites the original. The caller should trigger reindex + graph
    rebuild afterwards so the cleaned content re-enters RAG and the graph.

    Raises ``ValueError`` if normalization produces empty output, leaving the
    original file untouched (never replace good content with nothing).
    """
    from knowledge.normalizer import normalize_to_markdown

    path = resolve_workspace_document(relative_path, project_id)
    if not path.exists():
        raise FileNotFoundError("找不到指定文件")

    original = path.read_text(encoding="utf-8-sig")
    cleaned = normalize_to_markdown(original, strict=True)
    if not cleaned:
        raise ValueError("整理結果為空，已保留原文件")

    return apply_workspace_document_normalization(relative_path, cleaned, project_id)


def save_uploaded_document(
    filename: str,
    content: bytes,
    target_dir: str = "",
    project_id: str = "default",
    relative_path: str = "",
) -> dict[str, Any]:
    """Save an uploaded file into the workspace root.

    When ``relative_path`` is provided (e.g. ``subdir/a.md`` from a folder
    upload), preserve its directory structure under ``target_dir``. Otherwise
    fall back to the file's basename.
    """
    safe_name = Path(filename).name
    if not safe_name:
        raise ValueError("filename 不可為空")

    sub_path = _sanitize_relative_subpath(relative_path) if relative_path else Path(safe_name)
    base = Path(target_dir.strip()) if target_dir.strip() else Path()
    relative_path_obj = base / sub_path
    path = resolve_workspace_document(relative_path_obj.as_posix(), project_id)
    relative = path.relative_to(ensure_workspace_scaffold(project_id).resolve()).as_posix()
    decoded = content.decode("utf-8-sig")
    from knowledge.qa_nodes import is_qa_document, sync_entries_for_source

    # 覆蓋上傳已經在問答樹上的文件仍是 QA 文件；標成 upload 的話搬移與刪除都不會跟著更新節點。
    was_qa = path.exists() and is_qa_document(relative, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, decoded)
    upsert_document_meta(relative, project_id, source_type="qa" if was_qa else "upload")
    # 覆蓋上傳可能換了語言版本；清掉自動判斷的語言讓它重判。
    touch_document_meta(relative, project_id)
    if was_qa:
        sync_entries_for_source(relative, project_id)
    return _build_document_summary(path, project_id)


def save_uploaded_artifact(
    filename: str,
    content: bytes,
    target_dir: str = "raw",
    project_id: str = "default",
    relative_path: str = "",
) -> dict[str, Any]:
    """Save a binary artifact into the workspace without indexing it."""
    safe_name = Path(filename).name
    if not safe_name:
        raise ValueError("filename 不可為空")

    sub_path = _sanitize_relative_subpath(relative_path) if relative_path else Path(safe_name)
    base = Path(target_dir.strip()) if target_dir.strip() else Path()
    relative_path_obj = base / sub_path
    path = resolve_workspace_artifact(relative_path_obj.as_posix(), project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    stat = path.stat()
    return {
        "path": relative_path_obj.as_posix(),
        "title": path.stem,
        "extension": path.suffix.lower(),
        "size": stat.st_size,
        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "is_indexable": False,
        "is_indexed": False,
    }


def _resolve_note_parent(target_dir: str) -> Path:
    cleaned = target_dir.strip()
    if not cleaned:
        return Path("knowledge") / "notes"

    relative = Path(cleaned)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("target_dir 必須是 knowledge 內的相對路徑")
    return Path("knowledge") / relative


def save_workspace_note(
    title: str,
    content: str,
    project_id: str = "default",
    target_dir: str = "",
    note_format: str = "text",
) -> dict[str, Any]:
    """Create a manual note under the default notes directory or target directory.

    ``note_format="qa"`` stores the note in the ``knowledge/qa/`` namespace with
    ``source_type="qa"`` so it is managed by the QA subsystem; the content must
    already be QA markdown (``## question`` blocks with qa_metadata comments).
    """
    cleaned_title = title.strip()
    cleaned_content = content.strip()
    if not cleaned_title:
        raise ValueError("title 不可為空")
    if not cleaned_content:
        raise ValueError("content 不可為空")

    is_qa = note_format == "qa"
    if is_qa:
        from knowledge.qa_csv import parse_qa_markdown

        if not parse_qa_markdown(cleaned_content):
            raise ValueError("內容不是有效的 QA 格式（需要 ## 問題 標題與答案）")

    filename = Path(cleaned_title).name
    if filename != cleaned_title:
        raise ValueError("title 不可包含路徑")
    if not filename.lower().endswith(".md"):
        filename = f"{filename}.md"

    parent = Path("knowledge") / "qa" if is_qa else _resolve_note_parent(target_dir)
    relative_path = parent / filename
    path = resolve_workspace_document(relative_path.as_posix(), project_id)
    if path.exists():
        raise ValueError("文件已存在")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cleaned_content, encoding="utf-8")
    upsert_document_meta(
        relative_path.as_posix(), project_id, source_type="qa" if is_qa else "manual"
    )
    summary = _build_document_summary(path, project_id, content=cleaned_content)
    if is_qa:
        from knowledge.qa_nodes import create_node_for_source

        node = create_node_for_source(
            relative_path.as_posix(), Path(filename).stem, project_id
        )
        summary["qa_node_id"] = node["node_id"]
    return summary


def create_workspace_directory(relative_path: str, project_id: str = "default") -> dict[str, str]:
    """Create a directory under the workspace root."""
    root = ensure_workspace_scaffold(project_id).resolve()
    cleaned = relative_path.strip()
    if not cleaned:
        raise ValueError("path 不可為空")
    rel = Path(cleaned)
    if rel.is_absolute():
        raise ValueError("path 必須是相對路徑")
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise ValueError("path 不可超出 workspace")
    target.mkdir(parents=True, exist_ok=True)
    return {"status": "ok", "path": cleaned}


def delete_workspace_directory(relative_path: str, project_id: str = "default") -> dict[str, str]:
    """Delete a directory under the workspace root. Must be empty."""
    import shutil
    root = ensure_workspace_scaffold(project_id).resolve()
    cleaned = relative_path.strip()
    if not cleaned:
        raise ValueError("path 不可為空")
    rel = Path(cleaned)
    if rel.is_absolute():
        raise ValueError("path 必須是相對路徑")
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise ValueError("path 不可超出 workspace")
    if not target.is_dir():
        raise FileNotFoundError("找不到指定目錄")
    # Check if directory has files (allow removing dirs with only subdirs)
    has_files = any(p.is_file() for p in target.rglob("*"))
    if has_files:
        raise ValueError("目錄內仍有檔案，請先移除或移動檔案")
    shutil.rmtree(target)
    return {"status": "ok", "path": cleaned}


def delete_workspace_document(relative_path: str, project_id: str = "default") -> None:
    """Delete a document from the workspace."""
    path = resolve_workspace_document(relative_path, project_id)
    if not path.exists():
        raise FileNotFoundError("找不到指定文件")
    path.unlink()
    delete_document_meta(relative_path, project_id)


def move_workspace_document(source_path: str, target_path: str, project_id: str = "default") -> dict[str, Any]:
    """Rename or relocate a document within the workspace."""
    source = resolve_workspace_document(source_path, project_id)
    target = resolve_workspace_document(target_path, project_id)
    if not source.exists():
        raise FileNotFoundError("找不到來源文件")
    if source == target:
        return _build_document_summary(target, project_id)
    if target.exists():
        raise ValueError("目標路徑已存在")

    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    move_document_meta(source_path, target_path, project_id)
    return _build_document_summary(target, project_id)


def update_workspace_document_meta(
    relative_path: str,
    project_id: str = "default",
    *,
    enabled: bool | None = None,
    source_type: str | None = None,
    source_url: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Update persisted metadata for a workspace document.

    ``language``：zh／en／es 為手動指定；``"auto"`` 清掉指定，下次用到時依內容重判。
    """
    path = resolve_workspace_document(relative_path, project_id)
    if not path.exists():
        raise FileNotFoundError("找不到指定文件")

    kwargs: dict[str, Any] = {}
    if enabled is not None:
        kwargs["enabled"] = enabled
    if source_type is not None:
        kwargs["source_type"] = source_type
    if source_url is not None:
        kwargs["source_url"] = source_url
    if language is not None:
        kwargs["language"] = None if language == "auto" else language

    upsert_document_meta(relative_path, project_id, **kwargs)
    return _build_document_summary(path, project_id)


def _build_document_summary(
    path: Path,
    project_id: str = "default",
    content: str | None = None,
    index_state: dict[str, str] | None = None,
    qa_referenced_paths: set[str] | None = None,
    root: Path | None = None,
    core_paths: set[str] | None = None,
    doc_meta: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from knowledge.doc_meta import _resolved_entry

    if root is None:
        root = ensure_workspace_scaffold(project_id)
    relative_path = path.relative_to(root)
    stat = path.stat()
    relative_text = relative_path.as_posix()
    if core_paths is None:
        core_docs = get_core_documents(project_id)
        core_paths = {core_path.relative_to(root).as_posix() for core_path in core_docs.values()}

    if content is not None:
        preview_text = content
    else:
        try:
            with path.open("rb") as f:
                raw = f.read(1024)
            preview_text = raw.decode("utf-8-sig", errors="replace")
        except Exception:
            preview_text = ""

    is_indexable = is_indexable_document(path, project_id)

    # Determine if the file has been indexed by comparing its fingerprint
    # against the stored index state.
    is_indexed = False
    if is_indexable:
        state = index_state if index_state is not None else load_index_state(project_id)
        stored_fp = state.get(relative_text, "")
        if stored_fp:
            is_indexed = stored_fp == fingerprint_document(path)

    if doc_meta is not None:
        raw_entry = doc_meta.get(relative_text, {})
        document_meta = _resolved_entry(raw_entry)
    else:
        document_meta = get_document_meta(relative_text, project_id)

    qa_attached = False
    if document_meta["source_type"] == "qa":
        from knowledge.qa_nodes import referenced_source_paths

        paths = (
            qa_referenced_paths
            if qa_referenced_paths is not None
            else referenced_source_paths(project_id)
        )
        qa_attached = relative_text in paths

    return {
        "path": relative_text,
        "title": path.stem,
        "category": relative_path.parent.as_posix() if relative_path.parent != Path(".") else "",
        "extension": path.suffix.lower(),
        "size": stat.st_size,
        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "is_core": relative_text in core_paths or is_persona_core_relative_path(relative_text),
        "is_indexable": is_indexable,
        "is_indexed": is_indexed,
        "preview": " ".join(preview_text.split())[:140],
        "source_type": document_meta["source_type"],
        "source_url": document_meta["source_url"],
        "enabled": document_meta["enabled"],
        "created_at": document_meta["created_at"],
        "language": document_meta["language"],
        "language_source": document_meta["language_source"],
        "qa_attached": qa_attached,
        # 刪除確認要照實說原檔還在不在：工作區頁上傳與舊文件沒有備份。
        "has_original_backup": bool(document_meta["origin_path"])
        and (root / document_meta["origin_path"]).is_file(),
    }


def _parse_qa_markdown(content: str, relative_path: str) -> list[dict[str, str]]:
    """Return ``{path, question, answer}`` QA entries for a markdown source.

    Thin adapter over the shared :func:`knowledge.qa_csv.parse_qa_markdown`
    parser; drops the img/url metadata the flat entry list does not need.
    """
    return [
        {"path": relative_path, "question": entry["q"], "answer": entry["a"]}
        for entry in parse_qa_markdown(content)
    ]


def list_qa_entries(project_id: str = "default") -> list[dict[str, str]]:
    """Return every question/answer pair from enabled QA-sourced documents."""
    entries: list[dict[str, str]] = []
    for path in iter_knowledge_documents(project_id):
        relative_path = path.relative_to(ensure_workspace_scaffold(project_id)).as_posix()
        meta = get_document_meta(relative_path, project_id)
        if meta["source_type"] != "qa" or not meta["enabled"]:
            continue
        content = path.read_text(encoding="utf-8-sig")
        entries.extend(_parse_qa_markdown(content, relative_path))
    return entries


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


def _raw_relative_path(path: str, raw_root: Path) -> str:
    parts = path.split("/")
    # 反斜線在這裡只是檔名的一部分，但沒有這個檔案時多半是 Windows 路徑，一樣拒絕。
    # 真的有這個檔名時要放行，否則它移不掉，「全部匯入」也會整批失敗。
    if any(part in ("", ".", "..") for part in parts) or (
        "\\" in path and not (raw_root / path).is_file()
    ):
        raise ValueError("檔案路徑不正確")
    # 上傳回應給 raw/a.csv，等待清單給 a.csv，兩種都收；raw/ 底下真的有 raw 資料夾時以實際檔案為準。
    relative = path
    if parts[0] == "raw" and len(parts) > 1 and not (raw_root / path).is_file():
        relative = "/".join(parts[1:])
    if not (raw_root / relative).resolve().is_relative_to(raw_root.resolve()):
        raise ValueError("檔案路徑不正確")
    return relative


def normalize_raw_paths(paths: Iterable[str], project_id: str = "default") -> list[str]:
    """Return client-supplied paths relative to raw/, deduplicated, rejecting traversal."""
    raw_root = ensure_workspace_scaffold(project_id) / "raw"
    return list(dict.fromkeys(_raw_relative_path(path, raw_root) for path in paths))


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
_REASON_NO_QUESTIONS = "這份問答表沒有任何題目"
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


def _qa_table_target(filename: str, project_id: str, keep_csv: bool = False) -> Path:
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


def _refuse_unclear_questions(entries: list[dict[str, Any]]) -> None:
    """Refuse rows the quick Q&A cannot show correctly, instead of guessing.

    編輯器一題只顯示一個答案，同一題有兩個答案時另一個會看不到，AI 卻兩個都查得到。
    沒有題目的列在選單上只會是一顆「未命名問題」。
    """
    answers: dict[str, str] = {}
    for entry in entries:
        question, answer = entry["q"].strip(), entry["a"].strip()
        if question == UNTITLED_QUESTION:
            raise _ImportRefused(
                f"有一列只有答案、沒有題目（「{' '.join(answer.split())[:20]}」），"
                "請補上題目後重新上傳"
            )
        if answers.setdefault(question, answer) != answer:
            short = " ".join(question.split())[:40]
            raise _ImportRefused(f"「{short}」這一題在檔案裡有不同的答案，請只留一個後重新上傳")


def _render_qa_document(csv_bytes: bytes, target: Path) -> str:
    """Render a QA table in ``target``'s format, refusing what the format cannot hold.

    轉成 Markdown 後，答案裡的 ## 行和多行題目會被切成別的題目。寫入前先讀回比對（和
    ingest-source 同樣的做法），否則題目會默默拆壞，重傳時還會蓋掉原本正確的內容。
    """
    normalized = normalize_qa_csv_rows(csv_bytes)
    entries = parse_qa_csv(normalized) if normalized is not None else []
    if normalized is None or not entries:
        raise _ImportRefused(_REASON_NO_QUESTIONS)
    _refuse_unclear_questions(entries)
    if target.suffix == ".csv":
        return normalized.decode("utf-8")

    markdown = convert_csv_to_qa_markdown(csv_bytes)
    expected = qa_entry_values(entries)
    actual = qa_entry_values(parse_qa_markdown(markdown))
    if expected != actual:
        broken = next((e for e, a in zip(expected, actual) if e != a), expected[-1])
        question = " ".join(broken[0].split())[:40]
        raise _ImportRefused(
            f"「{question}」這題的答案裡有「##」或「```」符號，或題目有換行，"
            "請在檔案裡刪掉這些符號或換行，存檔後重新上傳"
        )
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
    from knowledge.qa_nodes import (
        create_node_for_source,
        find_language_category,
        is_qa_document,
        is_source_referenced,
        node_label,
        place_questions_by_path,
        refill_emptied_node,
        sync_entries_for_source,
    )
    from knowledge.qa_csv import qa_csv_row_extras
    from knowledge.qa_merged import MergedSaveError, merge_reupload

    root = ensure_workspace_scaffold(project_id)
    src = root / "raw" / relative
    if not src.is_file():
        raise _ImportRefused(_REASON_MISSING)
    if src.suffix.lower() not in SUPPORTED_SUFFIXES:
        allowed = "、".join(sorted(SUPPORTED_SUFFIXES))
        raise _ImportRefused(f"這個格式不支援，請改用 {allowed}")

    report("normalizing")

    origin_bytes = src.read_bytes()
    qa_csv = qa_table_csv_bytes(src, origin_bytes)
    is_qa = qa_csv is not None
    extras = qa_csv_row_extras(qa_csv) if is_qa else {}
    target_rel = (
        _qa_table_target(
            src.name, project_id, keep_csv=any(row["language"] for row in extras.values()),
        )
        if is_qa
        else (Path("knowledge") / relative).with_suffix(".md")
    )
    target = target_rel.as_posix()
    if target in claimed_targets:
        # 同名不同副檔名（a.csv、a.xlsx）或不同資料夾的問答表會存成同一份，後面的會蓋掉前面的。
        raise _ImportRefused(
            f"和同一批的 {claimed_targets[target]} 會存成同一份文件，請改檔名後再上傳"
        )

    if is_qa:
        content = _render_qa_document(qa_csv, target_rel)
    else:
        text = convert_to_text(src)
        if not text:
            raise _ImportRefused(_no_text_reason(src, origin_bytes))
        content = normalize_to_markdown(text) if normalize else text
        if not content.strip():
            raise _ImportRefused(_REASON_NO_TEXT)

    dest = resolve_workspace_document(target, project_id)
    origin_hash = hashlib.sha256(origin_bytes).hexdigest()
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
                merged = merge_reupload(target, parse_qa_csv(normalize_qa_csv_rows(qa_csv)), extras, project_id)
            except MergedSaveError as exc:
                raise _ImportRefused(exc.detail) from exc
            content = merged.content
            merge_counts = {"added": merged.added, "kept": merged.kept}
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
            if any(row["path"] for row in extras.values()):
                # 同一份表裡沒填 path 的題目，不論第一次匯入或重傳，都放以檔名命名的分類。
                parents = [node_label(category, project_id)] if category else []
                name_clashes = place_questions_by_path(
                    target,
                    {q: row["path"] or [*parents, target_rel.stem] for q, row in extras.items()},
                    project_id,
                )
                if referenced:
                    sync_entries_for_source(target, project_id)
            elif referenced:
                sync_entries_for_source(target, project_id)
            elif not refill_emptied_node(target, target_rel.stem, project_id):
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

    result = {
        "target": target,
        "kind": "qa" if is_qa else "document",
        "language": language,
        "updated": updated,
        **merge_counts,
        **({"name_clashes": name_clashes} if name_clashes else {}),
    }
    return {**result, **_qa_node_summary(target, project_id)} if is_qa else result


@project_model_entry("knowledge")
def commit_raw_documents(
    project_id: str = "default",
    on_progress: Callable[[str, str], None] | None = None,
    *,
    paths: Iterable[str] | None = None,
    normalize: bool = True,
    on_result: Callable[[str, dict[str, Any]], None] | None = None,
    on_skip: Callable[[str, str], None] | None = None,
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

    def _report(path: str, state: str) -> None:
        if on_progress:
            on_progress(path, state)

    committed: list[str] = []
    skipped: list[str] = []
    results: dict[str, dict[str, Any]] = {}
    skip_reasons: dict[str, str] = {}
    claimed_targets: dict[str, str] = {}
    for relative in relative_paths:
        try:
            result = _commit_raw_file(
                relative,
                project_id,
                normalize=normalize,
                claimed_targets=claimed_targets,
                report=partial(_report, relative),
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

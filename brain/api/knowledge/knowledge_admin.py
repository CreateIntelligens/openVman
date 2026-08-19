"""Workspace document management for the admin console."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

from knowledge.doc_meta import (
    delete_document_meta,
    get_document_meta,
    move_document_meta,
    touch_document_meta,
    upsert_document_meta,
)
from knowledge.indexer import fingerprint_document, load_index_state
from knowledge.qa_csv import parse_qa_markdown
from knowledge.workspace import (
    ensure_workspace_scaffold,
    get_core_documents,
    is_indexable_document,
    iter_knowledge_documents,
    iter_workspace_documents,
    resolve_workspace_artifact,
    resolve_workspace_document,
)
from personas.personas import is_persona_core_relative_path


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
    """Return all subdirectory paths under knowledge/, relative to workspace root."""
    root = ensure_workspace_scaffold(project_id)
    knowledge_dir = root / "knowledge"
    return sorted(
        p.relative_to(root).as_posix()
        for p in knowledge_dir.rglob("*")
        if p.is_dir()
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
    return _list_document_summaries(iter_knowledge_documents(project_id), project_id)


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
    path.write_text(content, encoding="utf-8")
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


def preview_workspace_document_normalization(
    relative_path: str,
    project_id: str = "default",
) -> dict[str, Any]:
    from knowledge.normalizer import normalize_to_markdown

    path = resolve_workspace_document(relative_path, project_id)
    if not path.exists():
        raise FileNotFoundError("找不到指定文件")

    original = path.read_text(encoding="utf-8-sig")
    cleaned = normalize_to_markdown(original)
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
    cleaned = normalize_to_markdown(original)
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
    decoded = content.decode("utf-8-sig")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(decoded, encoding="utf-8")
    upsert_document_meta(relative_path_obj.as_posix(), project_id, source_type="upload")
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
    if not str(target).startswith(str(root)):
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
    if not str(target).startswith(str(root)):
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
) -> dict[str, Any]:
    """Update persisted metadata for a workspace document."""
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
        "qa_attached": qa_attached,
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


def commit_raw_documents(
    project_id: str = "default",
    on_progress: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """Promote staged files from raw/ into knowledge/ (the 'commit' step).

    raw/ is a staging area (uploads land there un-indexed). Committing now runs
    each file through the *normalization pipeline*: convert any supported format
    to text (docx/xlsx/pdf/csv/md/txt), then LLM-clean it into tidy Obsidian
    Markdown, writing the result as a ``.md`` under knowledge/ preserving its
    sub-path. The caller then triggers reindex + graph rebuild so the cleaned
    docs enter RAG and the concept graph.

    Files whose format cannot be converted are left untouched in raw/ and
    reported under ``skipped`` (the user can see they did not enter the base).
    """
    from knowledge.converters import SUPPORTED_SUFFIXES, convert_to_text
    from knowledge.normalizer import normalize_to_markdown
    from knowledge.qa_csv import is_qa_csv

    root = ensure_workspace_scaffold(project_id)
    raw_root = root / "raw"
    if not raw_root.exists():
        return {"committed": [], "skipped": []}

    committed: list[str] = []
    skipped: list[str] = []
    for src in sorted(p for p in raw_root.rglob("*") if p.is_file()):
        rel_in_raw = src.relative_to(raw_root)
        rel_path_str = rel_in_raw.as_posix()

        def _report(state: str) -> None:
            if on_progress:
                on_progress(rel_path_str, state)

        if src.suffix.lower() not in SUPPORTED_SUFFIXES:
            _report("skipped")
            skipped.append(rel_path_str)
            continue

        _report("normalizing")

        origin_bytes = src.read_bytes()
        origin_hash = hashlib.sha256(origin_bytes).hexdigest()
        is_qa = src.suffix.lower() == ".csv" and is_qa_csv(origin_bytes)

        text = convert_to_text(src)
        if not text:
            # Unsupported in practice / extraction failed: leave it in raw/.
            _report("skipped")
            skipped.append(rel_path_str)
            continue

        if is_qa:
            # QA CSV conversion already emits structured per-question markdown
            # with qa_metadata comments; LLM cleaning would mangle them.
            cleaned = text
        else:
            cleaned = normalize_to_markdown(text)
        if not cleaned:
            _report("skipped")
            skipped.append(rel_path_str)
            continue

        # Output is always markdown regardless of the source format.
        if is_qa:
            target_rel = (Path("knowledge/qa") / rel_in_raw.name).with_suffix(".md")
        else:
            target_rel = (Path("knowledge") / rel_in_raw).with_suffix(".md")
        dest = resolve_workspace_document(target_rel.as_posix(), project_id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(cleaned, encoding="utf-8")
        archived_rel = _archive_original(src, rel_in_raw, root)
        upsert_document_meta(
            target_rel.as_posix(),
            project_id,
            source_type="qa" if is_qa else "upload",
            origin_path=archived_rel,
            origin_hash=origin_hash,
        )
        if is_qa:
            from knowledge.qa_nodes import create_node_for_source

            create_node_for_source(target_rel.as_posix(), target_rel.stem, project_id)
        committed.append(target_rel.as_posix())
        _report("committed")

    return {"committed": committed, "skipped": skipped}


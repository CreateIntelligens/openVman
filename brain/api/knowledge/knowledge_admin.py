"""Workspace document management for the admin console."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from knowledge.indexer import fingerprint_document, load_index_state
from knowledge.doc_meta import (
    delete_document_meta,
    get_document_meta,
    move_document_meta,
    touch_document_meta,
    upsert_document_meta,
)
from knowledge.workspace import (
    get_core_documents,
    ensure_workspace_scaffold,
    is_indexable_document,
    iter_knowledge_documents,
    iter_workspace_documents,
    resolve_workspace_artifact,
    resolve_workspace_document,
    get_workspace_root,
)
from personas.personas import is_persona_core_relative_path


def list_knowledge_base_directories(project_id: str = "default") -> list[str]:
    """Return all subdirectory paths under knowledge/, relative to workspace root."""
    root = ensure_workspace_scaffold(project_id)
    knowledge_dir = root / "knowledge"
    return sorted(
        p.relative_to(root).as_posix()
        for p in knowledge_dir.rglob("*")
        if p.is_dir()
    )


def list_knowledge_base_documents(project_id: str = "default") -> list[dict[str, Any]]:
    """Return documents under the workspace knowledge/ directory."""
    index_state = load_index_state(project_id)
    return [_build_document_summary(path, project_id, index_state=index_state) for path in iter_knowledge_documents(project_id)]


def list_workspace_documents(project_id: str = "default") -> list[dict[str, Any]]:
    """Return editable documents under the workspace."""
    ensure_workspace_scaffold(project_id)
    index_state = load_index_state(project_id)
    return [_build_document_summary(path, project_id, index_state=index_state) for path in iter_workspace_documents(project_id)]


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


def save_uploaded_document(
    filename: str,
    content: bytes,
    target_dir: str = "",
    project_id: str = "default",
) -> dict[str, Any]:
    """Save an uploaded file into the workspace root."""
    safe_name = Path(filename).name
    if not safe_name:
        raise ValueError("filename 不可為空")

    relative_path = Path(target_dir.strip()) / safe_name if target_dir.strip() else Path(safe_name)
    path = resolve_workspace_document(relative_path.as_posix(), project_id)
    decoded = content.decode("utf-8-sig")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(decoded, encoding="utf-8")
    upsert_document_meta(relative_path.as_posix(), project_id, source_type="upload")
    return _build_document_summary(path, project_id)


def save_uploaded_artifact(
    filename: str,
    content: bytes,
    target_dir: str = "raw",
    project_id: str = "default",
) -> dict[str, Any]:
    """Save a binary artifact into the workspace without indexing it."""
    safe_name = Path(filename).name
    if not safe_name:
        raise ValueError("filename 不可為空")

    relative_path = Path(target_dir.strip()) / safe_name if target_dir.strip() else Path(safe_name)
    path = resolve_workspace_artifact(relative_path.as_posix(), project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    stat = path.stat()
    return {
        "path": relative_path.as_posix(),
        "title": path.stem,
        "extension": path.suffix.lower(),
        "size": stat.st_size,
        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "is_indexable": False,
        "is_indexed": False,
    }


def save_workspace_note(title: str, content: str, project_id: str = "default") -> dict[str, Any]:
    """Create a manual note under knowledge/notes."""
    cleaned_title = title.strip()
    cleaned_content = content.strip()
    if not cleaned_title:
        raise ValueError("title 不可為空")
    if not cleaned_content:
        raise ValueError("content 不可為空")

    filename = Path(cleaned_title).name
    if filename != cleaned_title:
        raise ValueError("title 不可包含路徑")
    if not filename.lower().endswith(".md"):
        filename = f"{filename}.md"

    relative_path = Path("knowledge") / "notes" / filename
    path = resolve_workspace_document(relative_path.as_posix(), project_id)
    if path.exists():
        raise ValueError("文件已存在")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cleaned_content, encoding="utf-8")
    upsert_document_meta(relative_path.as_posix(), project_id, source_type="manual")
    return _build_document_summary(path, project_id, content=cleaned_content)


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
) -> dict[str, Any]:
    root = ensure_workspace_scaffold(project_id)
    relative_path = path.relative_to(root)
    stat = path.stat()
    relative_text = relative_path.as_posix()
    core_docs = get_core_documents(project_id)
    core_paths = {core_path.relative_to(root).as_posix() for core_path in core_docs.values()}
    preview_text = content if content is not None else path.read_text(encoding="utf-8-sig")
    is_indexable = is_indexable_document(path, project_id)

    # Determine if the file has been indexed by comparing its fingerprint
    # against the stored index state.
    is_indexed = False
    if is_indexable:
        state = index_state if index_state is not None else load_index_state(project_id)
        stored_fp = state.get(relative_text, "")
        if stored_fp:
            is_indexed = stored_fp == fingerprint_document(path)
    document_meta = get_document_meta(relative_text, project_id)

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
    }

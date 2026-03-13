"""Workspace document management for the admin console."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from workspace import (
    CORE_DOCUMENTS,
    ensure_workspace_scaffold,
    is_indexable_document,
    iter_workspace_documents,
    resolve_workspace_document,
)
from personas import is_persona_core_relative_path


def list_workspace_documents() -> list[dict[str, Any]]:
    """Return editable documents under the workspace."""
    ensure_workspace_scaffold()
    return [_build_document_summary(path) for path in iter_workspace_documents()]


def read_workspace_document(relative_path: str) -> dict[str, Any]:
    """Read a document from the workspace."""
    path = resolve_workspace_document(relative_path)
    content = path.read_text(encoding="utf-8-sig")
    summary = _build_document_summary(path)
    summary["content"] = content
    return summary


def save_workspace_document(relative_path: str, content: str) -> dict[str, Any]:
    """Create or overwrite a text document in the workspace."""
    path = resolve_workspace_document(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return _build_document_summary(path)


def save_uploaded_document(
    filename: str,
    content: bytes,
    target_dir: str = "",
) -> dict[str, Any]:
    """Save an uploaded file into the workspace root."""
    safe_name = Path(filename).name
    if not safe_name:
        raise ValueError("filename 不可為空")

    relative_path = Path(target_dir.strip()) / safe_name if target_dir.strip() else Path(safe_name)
    path = resolve_workspace_document(relative_path.as_posix())
    decoded = content.decode("utf-8-sig")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(decoded, encoding="utf-8")
    return _build_document_summary(path)


def move_workspace_document(source_path: str, target_path: str) -> dict[str, Any]:
    """Rename or relocate a document within the workspace."""
    source = resolve_workspace_document(source_path)
    target = resolve_workspace_document(target_path)
    if not source.exists():
        raise FileNotFoundError("找不到來源文件")
    if source == target:
        return _build_document_summary(target)
    if target.exists():
        raise ValueError("目標路徑已存在")

    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return _build_document_summary(target)


def _build_document_summary(path: Path) -> dict[str, Any]:
    root = ensure_workspace_scaffold()
    relative_path = path.relative_to(root)
    stat = path.stat()
    relative_text = relative_path.as_posix()
    core_paths = {core_path.relative_to(root).as_posix() for core_path in CORE_DOCUMENTS.values()}
    return {
        "path": relative_text,
        "title": path.stem,
        "category": relative_path.parent.as_posix() if relative_path.parent != Path(".") else "",
        "extension": path.suffix.lower(),
        "size": stat.st_size,
        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "is_core": relative_text in core_paths or is_persona_core_relative_path(relative_text),
        "is_indexable": is_indexable_document(path),
        "preview": _build_preview(path),
    }


def _build_preview(path: Path) -> str:
    content = path.read_text(encoding="utf-8-sig")
    snippet = " ".join(content.split())
    return snippet[:140]

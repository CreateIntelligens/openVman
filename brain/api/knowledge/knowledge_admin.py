"""Workspace document management for the admin console."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from knowledge.indexer import fingerprint_document, load_index_state
from knowledge.workspace import (
    get_core_documents,
    ensure_workspace_scaffold,
    is_indexable_document,
    iter_knowledge_documents,
    iter_workspace_documents,
    resolve_workspace_document,
    get_workspace_root,
)
from personas.personas import is_persona_core_relative_path


def ingest_text_content(
    content: str,
    metadata: dict[str, Any],
    project_id: str = "default",
) -> dict[str, Any]:
    """Save ingested text from Gateway into workspace/raw/ingested/ and return summary.

    This is the main entry point for Gateway's Web Crawler worker to push
    processed text into the Brain knowledge base.
    """
    if not content.strip():
        raise ValueError("content 不可為空")

    now = datetime.now(timezone.utc)
    ingested_at = now.isoformat(timespec="seconds")
    ts = now.strftime("%Y%m%d_%H%M%S")

    # Generate filename from source_url or timestamp
    source_url = metadata.get("source_url", "")
    if source_url:
        parsed = urlparse(source_url)
        slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", f"{parsed.netloc}{parsed.path}")
        slug = re.sub(r"_+", "_", slug).strip("_")[:120]
        filename = f"{slug}.md"
    else:
        filename = f"ingested_{ts}.md"

    # Build frontmatter
    extra_metadata = {k: v for k, v in metadata.items() if k != "source_url"}
    frontmatter_lines = [
        "---",
        f"source_url: {source_url or 'unknown'}",
        f"ingested_at: {ingested_at}",
        *(f"{k}: {v}" for k, v in extra_metadata.items()),
        "---",
        "",
    ]
    full_content = "\n".join(frontmatter_lines) + content

    # Save to workspace/raw/ingested/
    root = ensure_workspace_scaffold(project_id)
    ingested_dir = root / "raw" / "ingested"
    ingested_dir.mkdir(parents=True, exist_ok=True)

    target_path = ingested_dir / filename
    # Avoid overwriting -- append timestamp suffix if file exists
    if target_path.exists():
        target_path = ingested_dir / f"{Path(filename).stem}_{ts}.md"

    target_path.write_text(full_content, encoding="utf-8")

    relative_path = target_path.relative_to(root).as_posix()
    return {
        "status": "ok",
        "path": relative_path,
        "filename": target_path.name,
        "size": target_path.stat().st_size,
        "ingested_at": ingested_at,
    }


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
    return _build_document_summary(path, project_id)


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
    return _build_document_summary(target, project_id)


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
    }

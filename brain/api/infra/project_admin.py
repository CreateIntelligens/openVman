"""Project CRUD: list, create, delete, and inspect projects."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from infra.project_context import (
    generate_project_id,
    get_data_root,
    normalize_project_id,
    resolve_project_context,
)


def list_projects() -> list[dict[str, Any]]:
    """Return metadata for every project under data/projects/."""
    root = get_data_root()
    if not root.exists():
        return []
    projects: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        try:
            pid = normalize_project_id(path.name)
        except ValueError:
            continue
        projects.append(_build_project_info(pid))
    return projects


def create_project(label: str) -> dict[str, Any]:
    """Create a new project directory and scaffold its workspace."""
    clean_label = label.strip()
    if not clean_label:
        raise ValueError("專案名稱不可為空白")
    pid = _next_available_project_id(generate_project_id(clean_label))
    ctx = resolve_project_context(pid)

    from knowledge.workspace import ensure_workspace_scaffold

    ensure_workspace_scaffold(project_id=pid)

    # Write a project metadata label file
    meta_path = ctx.project_root / "project.label"
    meta_path.write_text(clean_label, encoding="utf-8")

    return {
        "status": "ok",
        "project_id": pid,
        "label": clean_label,
        "project_root": str(ctx.project_root),
    }


def delete_project(project_id: str) -> dict[str, Any]:
    """Delete a project. The 'default' project cannot be deleted."""
    pid = normalize_project_id(project_id)
    if pid == "default":
        raise ValueError("default 專案不可刪除")

    ctx = resolve_project_context(pid)
    if not ctx.project_root.exists():
        raise ValueError(f"專案 '{pid}' 不存在")

    shutil.rmtree(ctx.project_root)
    return {"status": "ok", "project_id": pid}


def get_project_info(project_id: str) -> dict[str, Any]:
    """Return metadata about a specific project."""
    pid = normalize_project_id(project_id)
    ctx = resolve_project_context(pid)
    if not ctx.project_root.exists():
        raise ValueError(f"專案 '{pid}' 不存在")
    return _build_project_info(pid)


def _build_project_info(project_id: str) -> dict[str, Any]:
    """Build a summary dict for a project."""
    ctx = resolve_project_context(project_id)
    label = _read_label(ctx.project_root)

    persona_count = 0
    personas_dir = ctx.workspace_root / "personas"
    if personas_dir.exists():
        persona_count = sum(
            1
            for p in personas_dir.iterdir()
            if p.is_dir() and (p / "SOUL.md").exists()
        )

    document_count = 0
    if ctx.workspace_root.exists():
        document_count = sum(
            1
            for p in ctx.workspace_root.rglob("*")
            if p.is_file() and p.suffix.lower() in {".md", ".txt", ".csv"}
        )

    has_db = ctx.session_db_path.exists()
    has_lancedb = ctx.lancedb_path.exists()

    return {
        "project_id": project_id,
        "label": label,
        "persona_count": persona_count,
        "document_count": document_count,
        "has_session_db": has_db,
        "has_lancedb": has_lancedb,
        "project_root": str(ctx.project_root),
    }


def _read_label(project_root: Path) -> str:
    """Read the project label file, falling back to the directory name."""
    label_path = project_root / "project.label"
    if label_path.exists():
        return label_path.read_text(encoding="utf-8").strip()
    return project_root.name


def _next_available_project_id(base_project_id: str) -> str:
    """Return a project ID, adding a numeric suffix when needed."""
    project_id = base_project_id
    counter = 2
    while resolve_project_context(project_id).workspace_root.exists():
        project_id = f"{base_project_id}-{counter}"
        counter += 1
    return project_id

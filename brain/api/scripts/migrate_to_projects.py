"""Migrate legacy flat data layout to per-project directory structure.

Legacy layout:
    data/workspace/          → data/projects/default/workspace/
    ~/.openclaw/lancedb/     → data/projects/default/lancedb/
    /data/sessions.db        → data/projects/default/sessions.db
    /data/knowledge_index_state.json → data/projects/default/knowledge_index_state.json

This script is idempotent — it only moves data if the source exists and the
destination does NOT exist.  Called once from main.py lifespan on startup.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_API_ROOT = Path(__file__).resolve().parents[1]
_DATA_ROOT = _API_ROOT.parent / "data"
_DEFAULT_PROJECT = _DATA_ROOT / "projects" / "default"

_MIGRATION_MARKER = _DEFAULT_PROJECT / ".migrated"


def run_migration() -> None:
    """Execute all migration steps.  Safe to call multiple times."""
    if _MIGRATION_MARKER.exists():
        return

    migrated_any = False

    migrated_any |= _migrate_workspace()
    migrated_any |= _migrate_lancedb()
    migrated_any |= _migrate_sessions_db()
    migrated_any |= _migrate_index_state()
    migrated_any |= _migrate_learnings()

    # Write marker so future startups skip entirely
    _DEFAULT_PROJECT.mkdir(parents=True, exist_ok=True)
    _MIGRATION_MARKER.write_text("1", encoding="utf-8")

    if migrated_any:
        logger.info("資料遷移完成 → data/projects/default/")
    else:
        logger.info("無需遷移（已是新目錄結構或首次啟動）")


def _migrate_workspace() -> bool:
    src = _DATA_ROOT / "workspace"
    dst = _DEFAULT_PROJECT / "workspace"
    return _move_if_needed(src, dst, "workspace")


def _migrate_lancedb() -> bool:
    src = Path.home() / ".openclaw" / "lancedb"
    dst = _DEFAULT_PROJECT / "lancedb"
    return _move_if_needed(src, dst, "lancedb")


def _migrate_sessions_db() -> bool:
    src = Path("/data/sessions.db")
    dst = _DEFAULT_PROJECT / "sessions.db"
    return _move_if_needed(src, dst, "sessions.db")


def _migrate_index_state() -> bool:
    src = Path("/data/knowledge_index_state.json")
    dst = _DEFAULT_PROJECT / "knowledge_index_state.json"
    return _move_if_needed(src, dst, "knowledge_index_state.json")


def _migrate_learnings() -> bool:
    """Move .learnings/*.md to workspace root for all projects."""
    projects_dir = _DATA_ROOT / "projects"
    if not projects_dir.exists():
        return False

    migrated = False
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        ws = project_dir / "workspace"
        learnings_dir = ws / ".learnings"
        if not learnings_dir.exists():
            continue
        for md_file in learnings_dir.glob("*.md"):
            target = ws / md_file.name
            if not target.exists():
                shutil.move(str(md_file), str(target))
                logger.info("遷移 %s → %s", md_file, target)
                migrated = True
        # Remove .learnings/ if empty
        if learnings_dir.exists() and not any(learnings_dir.iterdir()):
            learnings_dir.rmdir()
            logger.info("移除空目錄 %s", learnings_dir)
    return migrated


def _move_if_needed(src: Path, dst: Path, label: str) -> bool:
    """Move a file or directory from src to dst if src exists and dst does not."""
    if not src.exists() or dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(src), str(dst))
        logger.info("遷移 %s: %s → %s", label, src, dst)
        return True
    except Exception as exc:
        logger.warning("遷移 %s 失敗: %s", label, exc)
        return False

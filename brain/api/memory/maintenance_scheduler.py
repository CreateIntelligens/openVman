"""Admin-owned maintenance for projects receiving turns in chat workers."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

from config import get_settings
from infra.project_context import get_data_root
from memory.memory_governance import maybe_run_memory_maintenance

logger = logging.getLogger(__name__)


def _activity(path: Path) -> tuple:
    # Read the WAL through SQLite; copying/stat-ing sessions.db misses live turns.
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as conn:
        return conn.execute(
            "SELECT MAX(id), COUNT(*) FROM conversation_messages"
        ).fetchone() + conn.execute(
            "SELECT MAX(updated_at) FROM conversations"
        ).fetchone()


def maintain_active_projects(seen: dict[str, tuple]) -> None:
    if get_settings().brain_role != "admin":
        return
    for path in sorted(get_data_root().glob("*/sessions.db")):
        project_id = path.parent.name
        try:
            activity = _activity(path)
            if activity == seen.get(project_id):
                continue
            result = maybe_run_memory_maintenance(True, project_id)
            if result.get("status") == "ok":
                # Capture before maintenance so a concurrent new turn runs next tick.
                seen[project_id] = activity
        except Exception:
            logger.exception("scheduled memory maintenance failed: %s", project_id)


def start_maintenance_scheduler() -> asyncio.Task | None:
    cfg = get_settings()
    if cfg.brain_role != "admin":
        return None

    async def run() -> None:
        seen: dict[str, tuple] = {}
        while True:
            await asyncio.sleep(max(1, cfg.memory_maintenance_interval_seconds))
            await asyncio.to_thread(maintain_active_projects, seen)

    return asyncio.create_task(run())

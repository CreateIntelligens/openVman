"""Back up chat sessions per project, split by language (VH-389).

JTI 的資料備份是把整個 Mongo 同步到另一個庫；openVman 的對話存在每個專案
各自的 SQLite，所以這裡改成「定期把對話匯出成檔案」：每次備份一個目錄，
底下每個專案一個子目錄，依 session 語言（最後一則使用者訊息）分成
zh.jsonl／en.jsonl／es.jsonl，每行一個 session 連同全部訊息。

備份放在 Brain 的資料卷底下，擋得住誤刪與程式寫壞，擋不住整顆磁碟壞掉；
要異地備份得另外把這個目錄同步出去。
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config import get_settings
from infra.project_context import get_data_root
from memory.language_detect import LANGUAGES
from memory.memory import get_session_store
from protocol.history import serialize_history_messages

logger = logging.getLogger(__name__)

MANIFEST = "manifest.json"
_lock = threading.Lock()


class BackupInProgressError(RuntimeError):
    """Another backup is already running; only one may run at a time."""


def backup_root() -> Path:
    configured = get_settings().session_backup_dir.strip()
    return Path(configured) if configured else get_data_root().parent / "backups" / "sessions"


def _project_ids() -> list[str]:
    root = get_data_root()
    if not root.exists():
        return []
    # 只看已經有 sessions.db 的專案；呼叫 get_session_store 會替沒有的專案建空庫。
    return sorted(
        path.name for path in root.iterdir()
        if path.is_dir() and (path / "sessions.db").exists()
    )


def _collect(project_id: str) -> dict[str, list[dict[str, Any]]]:
    store = get_session_store(project_id)
    by_language: dict[str, list[dict[str, Any]]] = {lang: [] for lang in LANGUAGES}
    for session in store.snapshot_sessions():
        session["messages"] = serialize_history_messages(session["messages"])
        by_language.setdefault(str(session["language"]), []).append(session)
    return by_language


def run_backup(*, dry_run: bool = False, trigger: str = "manual") -> dict[str, Any]:
    """Export every project's sessions; with ``dry_run`` only count them."""
    if not _lock.acquire(blocking=False):
        raise BackupInProgressError("已有備份正在執行")
    try:
        return _run_backup_locked(dry_run=dry_run, trigger=trigger)
    finally:
        _lock.release()


def _run_backup_locked(*, dry_run: bool, trigger: str) -> dict[str, Any]:
    started = datetime.now(ZoneInfo("Asia/Taipei"))
    backup_id = started.strftime("%Y%m%d-%H%M%S")
    root = backup_root()
    # 先寫到暫存目錄，全部完成才改名；中途失敗不會留下看似完整的備份。
    staging = root / f".{backup_id}.partial"
    projects: list[dict[str, Any]] = []

    for project_id in _project_ids():
        by_language = _collect(project_id)
        counts = {lang: len(sessions) for lang, sessions in by_language.items()}
        messages = sum(
            len(session["messages"])
            for sessions in by_language.values()
            for session in sessions
        )
        projects.append({"project_id": project_id, "sessions": counts, "messages": messages})
        if dry_run:
            continue
        project_dir = staging / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        for lang, sessions in by_language.items():
            if not sessions:
                continue
            with open(project_dir / f"{lang}.jsonl", "w", encoding="utf-8") as fh:
                for session in sessions:
                    fh.write(json.dumps(session, ensure_ascii=False) + "\n")

    manifest = {
        "backup_id": backup_id,
        "created_at": started.isoformat(),
        "trigger": trigger,
        "dry_run": dry_run,
        "projects": projects,
        "total_sessions": sum(sum(p["sessions"].values()) for p in projects),
        "total_messages": sum(p["messages"] for p in projects),
    }
    if dry_run:
        return manifest

    staging.mkdir(parents=True, exist_ok=True)
    (staging / MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8",
    )
    staging.rename(root / backup_id)
    removed = _prune(root)
    logger.info(json.dumps({
        "event": "session_backup_done",
        "backup_id": backup_id,
        "trigger": trigger,
        "total_sessions": manifest["total_sessions"],
        "pruned": removed,
    }))
    return manifest


def _prune(root: Path) -> list[str]:
    keep = get_settings().session_backup_keep
    backups = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    stale = backups[:-keep] if keep > 0 else []
    for path in stale:
        shutil.rmtree(path)
    # 前一次當掉留下的暫存目錄也清掉。
    for path in root.glob(".*.partial"):
        shutil.rmtree(path)
    return [path.name for path in stale]


def list_backups() -> list[dict[str, Any]]:
    root = backup_root()
    if not root.exists():
        return []
    backups: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), reverse=True):
        manifest = path / MANIFEST
        if path.name.startswith(".") or not manifest.exists():
            continue
        backups.append(json.loads(manifest.read_text(encoding="utf-8")))
    return backups


def backup_running() -> bool:
    return _lock.locked()


def _seconds_until(hour: int, tz: ZoneInfo) -> float:
    now = datetime.now(tz)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def start_backup_scheduler() -> asyncio.Task | None:
    """Run one backup a day at ``session_backup_hour`` (Asia/Taipei)."""
    cfg = get_settings()
    if not cfg.session_backup_enabled:
        return None
    tz = ZoneInfo("Asia/Taipei")

    async def _loop() -> None:
        while True:
            await asyncio.sleep(_seconds_until(cfg.session_backup_hour, tz))
            try:
                await asyncio.to_thread(run_backup, trigger="schedule")
            except BackupInProgressError:
                logger.info("scheduled session backup skipped: another is running")
            except Exception:
                logger.exception("scheduled session backup failed")

    return asyncio.create_task(_loop())

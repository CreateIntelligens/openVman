"""Recall trace recorder — non-blocking JSONL append for dreaming consolidation.

Records which memories were retrieved, for what query, and when.
This data feeds the Light and REM phases of the dreaming cycle.
"""

from __future__ import annotations

import atexit
import json
import logging
import queue
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import get_settings
from memory.dreaming.paths import dreams_dir

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single-writer background thread + bounded queue
# ---------------------------------------------------------------------------

_write_queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=2000)
_writer_started = False
_writer_lock = threading.Lock()


def _ensure_writer() -> None:
    global _writer_started
    if _writer_started:
        return
    with _writer_lock:
        if _writer_started:
            return
        t = threading.Thread(target=_writer_loop, daemon=True)
        t.start()
        _writer_started = True


def _writer_loop() -> None:
    """Drain the queue and batch-write entries to JSONL."""
    while True:
        batch: list[tuple[str, dict[str, Any]]] = []
        try:
            batch.append(_write_queue.get(timeout=5.0))
            # Drain remaining items without blocking
            while not _write_queue.empty():
                try:
                    batch.append(_write_queue.get_nowait())
                except queue.Empty:
                    break
        except queue.Empty:
            continue

        # Group by project_id and write
        by_project: dict[str, list[str]] = {}
        for pid, entry in batch:
            line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
            by_project.setdefault(pid, []).append(line)

        for pid, lines in by_project.items():
            try:
                path = _traces_dir(pid) / "recall-traces.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
            except Exception as exc:
                logger.debug("recall trace write failed: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trace(
    *,
    query: str,
    persona_id: str,
    project_id: str,
    table_name: str,
    results: list[dict[str, Any]],
) -> None:
    """Enqueue a recall trace entry (non-blocking, single writer thread)."""
    cfg = get_settings()
    if not cfg.dreaming_enabled:
        return

    _ensure_writer()
    entry = _build_entry(query, persona_id, project_id, table_name, results)
    try:
        _write_queue.put_nowait((project_id, entry))
    except queue.Full:
        logger.debug("recall trace queue full, dropping entry")


def read_traces(
    project_id: str = "default",
    days: int | None = None,
) -> list[dict[str, Any]]:
    """Read recall trace entries within the last *days* (default: lookback_days)."""
    cfg = get_settings()
    if days is None:
        days = cfg.dreaming_lookback_days

    traces_dir = _traces_dir(project_id)
    if not traces_dir.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries: list[dict[str, Any]] = []

    for path in sorted(traces_dir.glob("recall-traces*.jsonl")):
        entries.extend(_parse_jsonl(path, cutoff))

    return entries


def rotate_traces(project_id: str = "default") -> int:
    """Rotate the active trace file and clean up old rotated files."""
    traces_dir = _traces_dir(project_id)
    active = traces_dir / "recall-traces.jsonl"

    if active.exists() and active.stat().st_size > 0:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rotated = traces_dir / f"recall-traces-{today}.jsonl"

        if rotated.exists():
            with open(rotated, "a", encoding="utf-8") as dst:
                dst.write(active.read_text(encoding="utf-8"))
            active.unlink()
        else:
            active.rename(rotated)

    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    deleted = 0
    for path in traces_dir.glob("recall-traces-*.jsonl"):
        try:
            date_str = path.stem.split("-")[-3:]
            file_date = datetime.strptime("-".join(date_str), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if file_date < cutoff:
                path.unlink()
                deleted += 1
        except (ValueError, IndexError):
            continue

    return deleted


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _traces_dir(project_id: str) -> Path:
    return dreams_dir(project_id)


def _build_entry(
    query: str,
    persona_id: str,
    project_id: str,
    table_name: str,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    compact = [
        {
            "text": str(r.get("text", ""))[:200],
            "score": r.get("_distance", r.get("score", 0.0)),
            "id": str(r.get("id", "")),
        }
        for r in results[:10]
    ]
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "query": query[:500],
        "persona": persona_id,
        "project": project_id,
        "table": table_name,
        "results": compact,
    }


def _parse_jsonl(path: Path, cutoff: datetime) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in (raw.strip() for raw in f if raw.strip()):
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry.get("ts", ""))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= cutoff:
                        entries.append(entry)
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
    except OSError as exc:
        logger.debug("failed to read trace file %s: %s", path, exc)
    return entries

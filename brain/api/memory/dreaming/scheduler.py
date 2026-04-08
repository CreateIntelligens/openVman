"""Dreaming scheduler — orchestrate Light → Deep → REM phases.

Provides a cron-based scheduler using asyncio (no APScheduler dependency),
timezone-aware scheduling, and a manual trigger endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config import get_settings
from knowledge.workspace import get_workspace_root
from memory.dreaming.paths import dreams_dir
from memory.dreaming.recall_tracker import rotate_traces

logger = logging.getLogger(__name__)

_last_run: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Cron specification
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CronSpec:
    """Simple cron spec — hour and minute only."""
    minute: int | None = None
    minute_step: int | None = None
    hour: int | None = None

    def matches(self, h: int, m: int) -> bool:
        return (
            (self.hour is None or h == self.hour) and
            (self.minute is None or m == self.minute) and
            (self.minute_step is None or m % self.minute_step == 0)
        )


def _parse_cron(expr: str) -> CronSpec:
    """Parse minute and hour from cron string (e.g. '0 3 * * *', '*/5 * * * *')."""
    parts = expr.strip().split()
    if len(parts) < 2:
        return CronSpec()

    m_str, h_str = parts[:2]

    minute, minute_step = None, None
    if m_str.startswith("*/"):
        minute_step = int(m_str[2:])
    elif m_str != "*":
        minute = int(m_str)

    hour = None if h_str == "*" else int(h_str)
    return CronSpec(minute=minute, minute_step=minute_step, hour=hour)


def _get_tz(tz_name: str) -> ZoneInfo | timezone:
    """Resolve timezone name, falling back to UTC on failure."""
    if not tz_name:
        return timezone.utc

    # Handle "UTC+N" / "UTC-N" fixed-offset
    s = tz_name.strip().upper()
    if s == "UTC":
        return timezone.utc
    if s.startswith("UTC") and len(s) > 3:
        try:
            return timezone(timedelta(hours=int(s[3:])))
        except (ValueError, OverflowError):
            pass

    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning("invalid timezone %r, fallback to UTC", tz_name)
        return timezone.utc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_dreaming_cycle(
    project_id: str = "default",
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Execute a full Light → Deep → REM cycle synchronously."""
    from .light_phase import run_light_phase
    from .deep_phase import run_deep_phase
    from .rem_phase import run_rem_phase

    cfg = get_settings()
    tz = _get_tz(cfg.dreaming_timezone)

    # Skip if already ran today (unless forced)
    if not force and _already_ran_today(project_id, tz):
        return {
            "status": "skipped",
            "reason": "already_ran_today",
            "project_id": project_id,
        }

    start = datetime.now(timezone.utc)
    results: dict[str, Any] = {
        "project_id": project_id,
        "status": "ok",
        "rotated_old_files": rotate_traces(project_id),
    }

    try:
        results["light"] = run_light_phase(project_id)
        results["deep"] = run_deep_phase(project_id)
        results["rem"] = run_rem_phase(project_id)
    except Exception as exc:
        logger.error("dreaming cycle failed: %s", exc, exc_info=True)
        results.update({"status": "error", "error": str(exc)})

    end = datetime.now(timezone.utc)
    results.update({
        "started_at": start.isoformat(),
        "completed_at": end.isoformat(),
        "duration_seconds": round((end - start).total_seconds(), 2),
    })

    _last_run[project_id] = results
    _write_run_state(project_id, results)
    return results


def get_dreaming_status(project_id: str = "default") -> dict[str, Any]:
    """Return the current dreaming status for a project."""
    cfg = get_settings()
    cron = _parse_cron(cfg.dreaming_cron)
    tz = _get_tz(cfg.dreaming_timezone)
    last = _get_last_run(project_id)

    return {
        "enabled": cfg.dreaming_enabled,
        "cron": cfg.dreaming_cron,
        "timezone": cfg.dreaming_timezone,
        "next_run": _compute_next_run(cron, tz),
        "last_run": last,
        "phase_stats": _extract_phase_stats(last),
        "config": _build_status_config(cfg),
    }


def get_latest_report(project_id: str = "default") -> str:
    """Return the latest Deep phase report content, or empty string."""
    report_dir = get_workspace_root(project_id) / "dreaming" / "deep"
    reports = sorted(report_dir.glob("*.md"), reverse=True) if report_dir.exists() else []
    return reports[0].read_text(encoding="utf-8") if reports else ""


def get_candidates_preview(project_id: str = "default") -> list[dict[str, Any]]:
    """Return the current candidates without promoting."""
    path = _dreams_dir(project_id) / "candidates.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# Scheduler loop
# ---------------------------------------------------------------------------

async def start_dreaming_scheduler(app: Any) -> None:
    """Start background scheduler loop."""
    cfg = get_settings()
    if not (cfg.dreaming_enabled and cfg.dreaming_projects):
        return

    cron, tz = _parse_cron(cfg.dreaming_cron), _get_tz(cfg.dreaming_timezone)
    logger.info("dreaming scheduler: starting (cron=%s, tz=%s)", cfg.dreaming_cron, cfg.dreaming_timezone)

    async def _loop():
        last_tick = None
        while True:
            await asyncio.sleep(30)
            now = datetime.now(tz)
            tick = now.replace(second=0, microsecond=0)
            if tick != last_tick and cron.matches(now.hour, now.minute):
                last_tick = tick
                for pid in cfg.dreaming_projects:
                    logger.info("dreaming scheduler: triggering project=%s", pid)
                    await asyncio.to_thread(run_dreaming_cycle, pid)

    app.state.dreaming_task = asyncio.create_task(_loop())


def _compute_next_run(cron: CronSpec, tz: ZoneInfo | timezone) -> str | None:
    """Compute the next matching time string."""
    candidate = datetime.now(tz).replace(second=0, microsecond=0)
    for _ in range(2880):  # Scan 48 hours
        candidate += timedelta(minutes=1)
        if cron.matches(candidate.hour, candidate.minute):
            return candidate.isoformat()
    return None


# ---------------------------------------------------------------------------
# Phase stats extraction
# ---------------------------------------------------------------------------

def _extract_phase_stats(last_run: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extract summary stats from last run results."""
    if not last_run:
        return None
    light = last_run.get("light", {})
    deep = last_run.get("deep", {})
    rem = last_run.get("rem", {})
    return {
        "candidate_count": light.get("candidate_count", 0),
        "fragment_count": light.get("fragment_count", 0),
        "promoted_count": deep.get("promoted_count", 0),
        "qualified_count": deep.get("qualified_count", 0),
        "theme_count": rem.get("theme_count", 0),
        "duration_seconds": last_run.get("duration_seconds", 0),
    }


def _get_last_run(project_id: str) -> dict[str, Any] | None:
    return _last_run.get(project_id) or _read_run_state(project_id)


def _already_ran_today(project_id: str, tz: ZoneInfo | timezone) -> bool:
    last_run = _get_last_run(project_id)
    if not last_run or last_run.get("status") != "ok":
        return False

    completed_date = last_run.get("completed_at", "")[:10]
    today = datetime.now(tz).date().isoformat()
    return completed_date == today


def _build_status_config(cfg: Any) -> dict[str, Any]:
    return {
        "lookback_days": cfg.dreaming_lookback_days,
        "min_score": cfg.dreaming_min_score,
        "min_recall_count": cfg.dreaming_min_recall_count,
        "candidate_limit": cfg.dreaming_candidate_limit,
        "similarity_threshold": cfg.dreaming_similarity_threshold,
    }


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _write_run_state(project_id: str, state: dict[str, Any]) -> None:
    path = _dreams_dir(project_id) / "last-run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


def _read_run_state(project_id: str) -> dict[str, Any] | None:
    path = _dreams_dir(project_id) / "last-run.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (json.JSONDecodeError, OSError):
        return None


def _dreams_dir(project_id: str) -> Path:
    return dreams_dir(project_id)

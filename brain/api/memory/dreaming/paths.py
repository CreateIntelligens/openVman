"""Shared path helpers and constants for the dreaming subsystem."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from config import get_settings
from knowledge.workspace import get_workspace_root

logger = logging.getLogger(__name__)

DATE_STEM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SOURCE_DREAMING = "dreaming"
TABLE_MEMORIES = "memories"
TABLE_KNOWLEDGE = "knowledge"


def resolve_timezone(tz_name: str) -> ZoneInfo | timezone:
    """Resolve IANA names or UTC offsets, falling back to UTC on failure."""
    if not tz_name:
        return timezone.utc
    name = tz_name.strip().upper()
    if name == "UTC":
        return timezone.utc
    if name.startswith("UTC") and len(name) > 3:
        try:
            return timezone(timedelta(hours=int(name[3:])))
        except (ValueError, OverflowError):
            pass
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning("invalid timezone %r, fallback to UTC", tz_name)
        return timezone.utc


def dreaming_now(now: datetime | None = None) -> datetime:
    """Use the configured calendar; supplied naive timestamps represent UTC."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(resolve_timezone(get_settings().dreaming_timezone))


def dreams_dir(project_id: str) -> Path:
    """Return the .dreams state directory for a project."""
    return get_workspace_root(project_id) / "dreaming" / ".dreams"


def write_dreaming_report(
    project_id: str,
    phase: str,
    lines: list[str],
    *,
    now: datetime | None = None,
) -> Path:
    """Write a dated markdown report to dreaming/{phase}/YYYY-MM-DD.md."""
    today = dreaming_now(now).date().isoformat()
    report_path = get_workspace_root(project_id) / "dreaming" / phase / f"{today}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path

"""Timezone-safe calendar date helpers for dreaming state."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def completion_date_in_timezone(completed_at: str, tz: ZoneInfo | timezone) -> str:
    """Convert a stored ISO timestamp to the scheduler's local calendar date."""
    try:
        completed = datetime.fromisoformat(completed_at)
    except (TypeError, ValueError):
        return ""
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=timezone.utc)
    return completed.astimezone(tz).date().isoformat()

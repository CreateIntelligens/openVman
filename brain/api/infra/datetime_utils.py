"""Shared UTC datetime utilities for consistent timestamp handling."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now_iso() -> str:
    """Return current UTC time as ISO-formatted string with timezone."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is UTC-aware, assuming UTC if naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def normalize_iso_timestamp(raw: str | None) -> str:
    """Parse an ISO timestamp and normalize to UTC-aware ISO string.

    Returns empty string for empty/None input.
    Returns original string if parsing fails.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return text
    return ensure_utc(dt).isoformat(timespec="seconds")

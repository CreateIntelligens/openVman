"""Shared timestamp helpers for the account and registry repositories.

分出來是為了讓各個 repository 模組共用時間戳格式，而不必彼此 import 而
形成循環；例外階層在 repository_errors。
"""

from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

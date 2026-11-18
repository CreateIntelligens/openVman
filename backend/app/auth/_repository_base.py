"""Shared timestamp helpers for the account and registry repositories.

分出來是為了讓各個 repository 模組共用時間戳格式，而不必彼此 import 而
形成循環；例外階層在 repository_errors。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@contextmanager
def write_transaction(
    database: Any, connection: sqlite3.Connection | None = None,
) -> Iterator[sqlite3.Connection]:
    """Join the caller's open transaction, or run in a write transaction of our own.

    呼叫端要把好幾個 repository 的寫入放進同一個交易時傳 connection，
    任何一步失敗就全部回滾。
    """
    if connection is not None:
        yield connection
        return
    with database.transaction(write=True) as own:
        yield own

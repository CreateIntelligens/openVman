"""Shared primitives for the account and registry repositories.

分出來是為了讓各個 repository 模組共用例外階層與時間戳格式，而不必彼此
import——否則 embed key 模組要用 RepositoryError 就得倒過來 import 主模組，
形成循環。
"""

from __future__ import annotations

from datetime import datetime, timezone


class RepositoryError(RuntimeError):
    """Base class for deterministic repository failures."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

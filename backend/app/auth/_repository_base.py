"""Shared primitives for the account and registry repositories.

分出來是為了讓各個 repository 模組共用例外階層與時間戳格式，而不必彼此
import——否則 embed key 模組要用 RepositoryError 就得倒過來 import 主模組，
形成循環。
"""

from __future__ import annotations

from datetime import datetime, timezone


class RepositoryError(RuntimeError):
    """Base class for deterministic repository failures."""


class UsernameConflictError(RepositoryError):
    pass


class ResourceConflictError(RepositoryError):
    pass


class UserNotFoundError(RepositoryError):
    pass


class AdminAlreadyExistsError(RepositoryError):
    pass


class SelfProtectionError(RepositoryError):
    pass


class LastAdminError(RepositoryError):
    pass


class AccountEnabledError(RepositoryError):
    pass


class OwnedResourcesError(RepositoryError):
    def __init__(self, counts: dict[str, int]) -> None:
        super().__init__("account owns private resources")
        self.counts = counts


class InvalidResourceGrantError(RepositoryError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

"""Exception hierarchy shared by the account and registry repositories.

路由、腳本與各 repository 都從這裡取例外；獨立成模組是為了讓呼叫端不必
知道是哪個 repository 丟出的，也不必 import 私有的 _repository_base。
"""

from __future__ import annotations


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

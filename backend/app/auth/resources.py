"""Authoritative resource access resolution for account-owned data."""

from __future__ import annotations

from enum import StrEnum

from .models import (
    UNSCOPED_ADMIN,
    AccountRole,
    AccountType,
    AdminScope,
    ResourceRecord,
    ResourceType,
    UserRecord,
    is_at_least_admin,
)
from .repositories import AdminScopeRepository, ResourceRepository

_RESOURCE_NOT_FOUND = "Resource not found"


class ResourceAccess(StrEnum):
    READ = "read"
    EDIT = "edit"
    MUTATE = "mutate"


class ResourceNotFoundError(LookupError):
    """Hide whether a resource is missing or belongs to another account."""

    def __init__(self) -> None:
        super().__init__(_RESOURCE_NOT_FOUND)


def is_unrestricted_admin(account: UserRecord) -> bool:
    """Whether an account bypasses grant checks entirely."""
    return (
        account.account_type is AccountType.FORMAL
        and is_at_least_admin(account.role)
    )


def resolve_admin_scope(
    account: UserRecord,
    admin_scopes: AdminScopeRepository | None = None,
) -> AdminScope:
    """Load an administrator's ceiling; ROOT is never scoped.

    The repository is resolved from the shared runtime when the caller does
    not pass one. Defaulting to *enforcing* rather than to unscoped matters:
    a call site that forgets to thread the repository through must not
    silently regain unrestricted access.
    """
    if account.role is AccountRole.ROOT:
        return UNSCOPED_ADMIN
    if admin_scopes is None:
        # 函式內 import：runtime 會 import repositories，這裡在模組層 import
        # runtime 會讓 import 順序變脆弱。
        from .runtime import get_auth_runtime

        try:
            admin_scopes = get_auth_runtime().admin_scopes
        except Exception:  # noqa: BLE001 - 無 runtime（測試替身）時不設限
            return UNSCOPED_ADMIN
    return admin_scopes.get(account.id)


def resolve_resource(
    resources: ResourceRepository,
    account: UserRecord,
    resource_type: ResourceType,
    resource_id: str,
    *,
    access: ResourceAccess = ResourceAccess.READ,
    admin_scopes: AdminScopeRepository | None = None,
) -> ResourceRecord:
    """Resolve one accessible resource without disclosing foreign IDs."""
    record = resources.get(resource_type, resource_id)
    if record is None:
        raise ResourceNotFoundError

    if is_unrestricted_admin(account):
        scope = resolve_admin_scope(account, admin_scopes)
        if scope.allows(resource_type, resource_id):
            return record
        # 超出 ROOT 指派範圍的資源，對這個 admin 而言等同不存在——與其他
        # 越權情境回報一致，不洩漏「存在但不給你」這件事。
        raise ResourceNotFoundError
    if record.owner_user_id == account.id:
        return record
    grant_allows_access = access is ResourceAccess.READ or (
        access is ResourceAccess.EDIT
        and resource_type is ResourceType.PROJECT
        and account.admin_portal_access
    )
    if (
        grant_allows_access
        and resources.has_grant(account.id, resource_type, resource_id)
    ):
        return record
    raise ResourceNotFoundError


def list_accessible_resources(
    resources: ResourceRepository,
    account: UserRecord,
    resource_type: ResourceType,
    *,
    admin_scopes: AdminScopeRepository | None = None,
) -> list[ResourceRecord]:
    """List resources visible to an account using the same resolver rules."""
    if is_unrestricted_admin(account):
        records = resources.list_by_type(resource_type)
        scope = resolve_admin_scope(account, admin_scopes)
        if scope.scoped:
            allowed = scope.resource_ids(resource_type)
            return [record for record in records if record.resource_id in allowed]
        return records
    return resources.list_accessible(
        account.id,
        resource_type=resource_type,
    )

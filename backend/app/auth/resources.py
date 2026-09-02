"""Authoritative resource access resolution for account-owned data."""

from __future__ import annotations

from enum import StrEnum

from .models import (
    AccountType,
    ResourceRecord,
    ResourceType,
    UserRecord,
    is_at_least_admin,
)
from .repositories import ResourceRepository

_RESOURCE_NOT_FOUND = "Resource not found"


class ResourceAccess(StrEnum):
    READ = "read"
    EDIT = "edit"
    MUTATE = "mutate"


class ResourceNotFoundError(LookupError):
    """Hide whether a resource is missing or belongs to another account."""

    def __init__(self) -> None:
        super().__init__(_RESOURCE_NOT_FOUND)


def resolve_resource(
    resources: ResourceRepository,
    account: UserRecord,
    resource_type: ResourceType,
    resource_id: str,
    *,
    access: ResourceAccess = ResourceAccess.READ,
) -> ResourceRecord:
    """Resolve one accessible resource without disclosing foreign IDs."""
    record = resources.get(resource_type, resource_id)
    if record is None:
        raise ResourceNotFoundError

    if (
        account.account_type is AccountType.FORMAL
        and is_at_least_admin(account.role)
    ):
        return record
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
) -> list[ResourceRecord]:
    """List resources visible to an account using the same resolver rules."""
    if (
        account.account_type is AccountType.FORMAL
        and is_at_least_admin(account.role)
    ):
        return resources.list_by_type(resource_type)
    return resources.list_accessible(
        account.id,
        resource_type=resource_type,
    )

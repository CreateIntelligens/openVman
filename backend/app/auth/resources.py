"""Authoritative resource access resolution for account-owned data."""

from __future__ import annotations

from enum import StrEnum

from .models import (
    AccountRole,
    AccountType,
    ResourceRecord,
    ResourceType,
    ResourceVisibility,
    UserRecord,
)
from .repositories import ResourceRepository

_RESOURCE_NOT_FOUND = "Resource not found"


class ResourceAccess(StrEnum):
    READ = "read"
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

    if account.account_type is AccountType.FORMAL:
        if account.role is AccountRole.ADMIN:
            return record
        if record.owner_user_id == account.id:
            return record
        if (
            access is ResourceAccess.READ
            and record.visibility is ResourceVisibility.SYSTEM_PUBLIC
        ):
            return record
    if (
        account.account_type is AccountType.TEMPORARY
        and access is ResourceAccess.READ
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
    if account.account_type is AccountType.TEMPORARY:
        return resources.list_granted(
            account.id,
            resource_type=resource_type,
        )
    if account.role is AccountRole.ADMIN:
        return resources.list_by_type(resource_type)
    return resources.list_accessible(
        account.id,
        resource_type=resource_type,
    )

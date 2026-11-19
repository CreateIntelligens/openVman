"""Resource options an administrator can assign to an account."""

from __future__ import annotations

import json

from pydantic import Field

from .account_schemas import _StrictModel
from .models import (
    AccountRole,
    AdminScope,
    ResourceRecord,
    ResourceType,
    UserRecord,
)
from .runtime import AuthRuntime


class AccountAccessOption(_StrictModel):
    id: str
    label: str
    provider: str | None = None
    owner_project_id: str | None = None
    visibility: str = "global"
    vendor_name: str | None = None


class AccountAccessOptions(_StrictModel):
    projects: list[AccountAccessOption]
    avatar_characters: list[AccountAccessOption]
    custom_voices: list[AccountAccessOption]
    avatar_mascots: list[AccountAccessOption] = Field(default_factory=list)
    avatar_backgrounds: list[AccountAccessOption] = Field(default_factory=list)
    asr_engines: list[AccountAccessOption] = Field(default_factory=list)


def _resource_option(record: ResourceRecord) -> AccountAccessOption:
    try:
        metadata = json.loads(record.metadata_json)
    except (TypeError, ValueError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    label = metadata.get("label")
    provider = metadata.get("provider")
    return AccountAccessOption(
        id=record.resource_id,
        label=(
            label.strip()
            if isinstance(label, str) and label.strip()
            else record.resource_id
        ),
        provider=(
            provider.strip()
            if isinstance(provider, str) and provider.strip()
            else None
        ),
        owner_project_id=record.owner_project_id,
        visibility=record.visibility,
        vendor_name=record.vendor_name,
    )


def scoped_options(
    runtime: AuthRuntime,
    scope: AdminScope,
    resource_type: ResourceType,
    admin_user: UserRecord | None = None,
) -> list[AccountAccessOption]:
    """List assignable resources of one type, capped by the caller's scope."""
    records = runtime.resources.list_by_type(resource_type)
    if scope.scoped:
        allowed = scope.resource_ids(resource_type)
        allowed_projects = scope.resource_ids(ResourceType.PROJECT)
        records = [
            record for record in records
            if record.resource_id in allowed
            and (
                record.visibility != "project"
                or (record.owner_project_id and record.owner_project_id in allowed_projects)
            )
        ]
    elif admin_user is not None and admin_user.role is not AccountRole.ROOT:
        my_projects = {
            g.resource_id
            for g in runtime.account_access.list_grants(admin_user.id)
            if g.resource_type is ResourceType.PROJECT
        }
        records = [
            record for record in records
            if record.visibility != "project"
            or (record.owner_project_id and record.owner_project_id in my_projects)
        ]
    return [_resource_option(record) for record in records]

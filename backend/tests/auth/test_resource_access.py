from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.auth.models import (
    AccountRole,
    AccountType,
    ResourceRecord,
    ResourceType,
    ResourceVisibility,
    UserRecord,
)
from app.auth.resources import (
    ResourceAccess,
    ResourceNotFoundError,
    resolve_resource,
)


def _user(
    *,
    portal_access: bool,
    account_type: AccountType = AccountType.FORMAL,
) -> UserRecord:
    return UserRecord(
        id="user-a",
        username="user-a",
        username_normalized="user-a",
        password_hash="hash",
        role=AccountRole.USER,
        account_type=account_type,
        disabled=False,
        token_version=0,
        created_at="2026-09-01T00:00:00+00:00",
        updated_at="2026-09-01T00:00:00+00:00",
        created_by=None,
        admin_portal_access=portal_access,
    )


def _resource(
    resource_type: ResourceType = ResourceType.PROJECT,
) -> ResourceRecord:
    return ResourceRecord(
        resource_type=resource_type,
        resource_id="resource-a",
        owner_user_id="admin-a",
        visibility=ResourceVisibility.PRIVATE,
        created_at="2026-09-01T00:00:00+00:00",
        metadata_json="{}",
    )


def _resources(
    record: ResourceRecord,
    *,
    granted: bool = True,
    project_writes: frozenset[str] = frozenset({"edit_knowledge", "edit_settings"}),
) -> MagicMock:
    resources = MagicMock()
    resources.get.return_value = record
    resources.has_grant.side_effect = (
        lambda *_args, project_write=None: granted
        and (project_write is None or project_write in project_writes)
    )
    return resources


@pytest.mark.parametrize(
    "account_type",
    [AccountType.FORMAL, AccountType.TEMPORARY],
)
@pytest.mark.parametrize("access", [ResourceAccess.EDIT_KNOWLEDGE, ResourceAccess.EDIT_SETTINGS])
def test_portal_user_can_edit_a_granted_project(
    account_type: AccountType,
    access: ResourceAccess,
) -> None:
    project = _resource()

    resolved = resolve_resource(
        _resources(project),
        _user(portal_access=True, account_type=account_type),
        ResourceType.PROJECT,
        project.resource_id,
        access=access,
    )

    assert resolved is project


@pytest.mark.parametrize(
    ("project_writes", "granted"),
    [(frozenset(), True), (frozenset({"edit_knowledge"}), False)],
)
def test_project_edit_requires_matching_grant(
    project_writes: frozenset[str],
    granted: bool,
) -> None:
    project = _resource()

    with pytest.raises(ResourceNotFoundError):
        resolve_resource(
            _resources(project, granted=granted, project_writes=project_writes),
            _user(portal_access=True),
            ResourceType.PROJECT,
            project.resource_id,
            access=ResourceAccess.EDIT_KNOWLEDGE,
        )


def test_portal_access_does_not_allow_global_resource_mutation() -> None:
    voice = _resource(ResourceType.CUSTOM_VOICE)

    with pytest.raises(ResourceNotFoundError):
        resolve_resource(
            _resources(voice),
            _user(portal_access=True),
            ResourceType.CUSTOM_VOICE,
            voice.resource_id,
            access=ResourceAccess.EDIT_KNOWLEDGE,
        )

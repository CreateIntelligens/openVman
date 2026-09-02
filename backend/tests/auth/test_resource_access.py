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


def _resources(record: ResourceRecord, *, granted: bool = True) -> MagicMock:
    resources = MagicMock()
    resources.get.return_value = record
    resources.has_grant.return_value = granted
    return resources


@pytest.mark.parametrize(
    "account_type",
    [AccountType.FORMAL, AccountType.TEMPORARY],
)
def test_portal_user_can_edit_a_granted_project(
    account_type: AccountType,
) -> None:
    project = _resource()

    resolved = resolve_resource(
        _resources(project),
        _user(portal_access=True, account_type=account_type),
        ResourceType.PROJECT,
        project.resource_id,
        access=ResourceAccess.EDIT,
    )

    assert resolved is project


@pytest.mark.parametrize(
    ("portal_access", "granted"),
    [(False, True), (True, False)],
)
def test_project_edit_requires_portal_access_and_grant(
    portal_access: bool,
    granted: bool,
) -> None:
    project = _resource()

    with pytest.raises(ResourceNotFoundError):
        resolve_resource(
            _resources(project, granted=granted),
            _user(portal_access=portal_access),
            ResourceType.PROJECT,
            project.resource_id,
            access=ResourceAccess.EDIT,
        )


def test_portal_access_does_not_allow_global_resource_mutation() -> None:
    voice = _resource(ResourceType.CUSTOM_VOICE)

    with pytest.raises(ResourceNotFoundError):
        resolve_resource(
            _resources(voice),
            _user(portal_access=True),
            ResourceType.CUSTOM_VOICE,
            voice.resource_id,
            access=ResourceAccess.EDIT,
        )

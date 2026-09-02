"""ROOT hierarchy, privileged account operations, and audit contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    AuthTransport,
    CurrentAccount,
    require_admin,
    require_root,
)
from app.auth.models import (
    AccountRole,
    AccountType,
    ResourceType,
    ResourceVisibility,
    UserRecord,
    is_at_least_admin,
    role_at_least,
)
from app.auth.passwords import hash_password, verify_password
from app.auth.policy import (
    AccountPolicyError,
    ensure_can_create_role,
    ensure_can_manage_account,
)
from app.auth.routes import auth_router, users_router
from app.auth.runtime import AuthRuntime, build_auth_runtime, get_auth_runtime
from app.config import TTSRouterConfig

_ROOT_PASSWORD = "root-password"
_ADMIN_PASSWORD = "admin-password"
_USER_PASSWORD = "user-password"
_NEW_PASSWORD = "replacement-password"


@pytest.fixture()
def runtime(tmp_path: Path) -> AuthRuntime:
    return build_auth_runtime(
        TTSRouterConfig(
            _env_file=None,
            env="dev",
        session_jwt_secret="test-only-session-secret-for-tests-32",
            auth_database_path=str(tmp_path / "accounts.db"),
        )
    )


@pytest.fixture()
def client(runtime: AuthRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(users_router)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    return TestClient(app)


def _record(
    role: AccountRole,
    *,
    account_type: AccountType = AccountType.FORMAL,
    disabled: bool = False,
) -> UserRecord:
    return UserRecord(
        id=f"usr_{role.value}_{account_type.value}",
        username=f"{role.value}-{account_type.value}",
        username_normalized=f"{role.value}-{account_type.value}",
        password_hash="unused",
        role=role,
        account_type=account_type,
        disabled=disabled,
        token_version=0,
        created_at="created",
        updated_at="updated",
        created_by=None,
    )


def _root(runtime: AuthRuntime):
    return runtime.users.create_root(
        username="ai360",
        password_hash=hash_password(_ROOT_PASSWORD),
    )


def _create_admin(runtime: AuthRuntime, root_id: str, username: str = "admin"):
    return runtime.users.create(
        username=username,
        password_hash=hash_password(_ADMIN_PASSWORD),
        role=AccountRole.ADMIN,
        created_by=root_id,
    )


def _create_user(runtime: AuthRuntime, actor_id: str, username: str = "user"):
    return runtime.users.create(
        username=username,
        password_hash=hash_password(_USER_PASSWORD),
        role=AccountRole.USER,
        created_by=actor_id,
    )


def _headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _register_scoped_resources(runtime: AuthRuntime) -> dict[str, object]:
    for resource_type, resource_id in (
        (ResourceType.PROJECT, "project-a"),
        (ResourceType.AVATAR_CHARACTER, "character-a"),
        (ResourceType.CUSTOM_VOICE, "voice-a"),
    ):
        runtime.resources.register(
            resource_type=resource_type,
            resource_id=resource_id,
            owner_user_id=None,
            visibility=ResourceVisibility.SYSTEM_PUBLIC,
        )
    return {
        "grants": {
            "projects": ["project-a"],
            "avatar_characters": ["character-a"],
            "custom_voices": ["voice-a"],
            "avatar_mascots": [],
            "avatar_backgrounds": [],
        },
        "defaults": {
            "project_id": "project-a",
            "character_id": "character-a",
            "voice_provider": "indextts",
            "voice_id": "voice-a",
            "mascot_id": "",
            "background_id": "",
        },
    }


def test_role_helpers_and_dependencies_follow_the_three_level_hierarchy():
    root = _record(AccountRole.ROOT)
    admin = _record(AccountRole.ADMIN)
    user = _record(AccountRole.USER)

    assert role_at_least(AccountRole.ROOT, AccountRole.ADMIN) is True
    assert role_at_least(AccountRole.ADMIN, AccountRole.ROOT) is False
    assert is_at_least_admin(AccountRole.ROOT) is True
    assert is_at_least_admin(AccountRole.ADMIN) is True
    assert is_at_least_admin(AccountRole.USER) is False

    for actor in (root, admin):
        current = CurrentAccount(user=actor, transport=AuthTransport.BEARER)
        assert require_admin(current) is current
    with pytest.raises(HTTPException) as user_denial:
        require_admin(CurrentAccount(user=user, transport=AuthTransport.BEARER))
    assert user_denial.value.status_code == 403

    root_current = CurrentAccount(user=root, transport=AuthTransport.BEARER)
    assert require_root(root_current) is root_current
    with pytest.raises(HTTPException) as admin_denial:
        require_root(CurrentAccount(user=admin, transport=AuthTransport.BEARER))
    assert admin_denial.value.status_code == 403


@pytest.mark.parametrize(
    ("actor_role", "target_role", "target_type", "allowed"),
    [
        (AccountRole.ROOT, AccountRole.ADMIN, AccountType.FORMAL, True),
        (AccountRole.ROOT, AccountRole.USER, AccountType.FORMAL, True),
        (AccountRole.ROOT, AccountRole.USER, AccountType.TEMPORARY, True),
        (AccountRole.ADMIN, AccountRole.ROOT, AccountType.FORMAL, False),
        (AccountRole.ADMIN, AccountRole.ADMIN, AccountType.FORMAL, False),
        (AccountRole.ADMIN, AccountRole.USER, AccountType.FORMAL, True),
        (AccountRole.ADMIN, AccountRole.USER, AccountType.TEMPORARY, True),
        (AccountRole.USER, AccountRole.USER, AccountType.FORMAL, False),
    ],
)
def test_actor_target_management_policy_matrix(
    actor_role: AccountRole,
    target_role: AccountRole,
    target_type: AccountType,
    allowed: bool,
):
    actor = _record(actor_role)
    target = _record(target_role, account_type=target_type)

    if allowed:
        ensure_can_manage_account(actor, target)
    else:
        with pytest.raises(AccountPolicyError):
            ensure_can_manage_account(actor, target)


@pytest.mark.parametrize(
    ("actor_role", "new_role", "allowed"),
    [
        (AccountRole.ROOT, AccountRole.ADMIN, True),
        (AccountRole.ROOT, AccountRole.USER, True),
        (AccountRole.ROOT, AccountRole.ROOT, False),
        (AccountRole.ADMIN, AccountRole.ADMIN, False),
        (AccountRole.ADMIN, AccountRole.USER, True),
        (AccountRole.ADMIN, AccountRole.ROOT, False),
    ],
)
def test_create_role_policy_matrix(
    actor_role: AccountRole,
    new_role: AccountRole,
    allowed: bool,
):
    actor = _record(actor_role)
    if allowed:
        ensure_can_create_role(actor, new_role)
    else:
        with pytest.raises(AccountPolicyError):
            ensure_can_create_role(actor, new_role)


def test_root_creates_admin_while_admin_cannot_create_or_manage_admin(
    client: TestClient,
    runtime: AuthRuntime,
):
    root = _root(runtime)
    root_headers = _headers(client, "ai360", _ROOT_PASSWORD)
    created = client.post(
        "/api/users",
        headers=root_headers,
        json={
            "username": "managed-admin",
            "password": _ADMIN_PASSWORD,
            "role": "admin",
        },
    )

    assert created.status_code == 201
    admin = created.json()
    assert admin["role"] == "admin"
    assert admin["created_by"] == root.id
    assert "password" not in created.text.casefold()
    assert "hash" not in created.text.casefold()

    admin_headers = _headers(client, "managed-admin", _ADMIN_PASSWORD)
    audit_before = runtime.auth_audit.list()
    denied_create = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "forbidden-admin",
            "password": _ADMIN_PASSWORD,
            "role": "admin",
        },
    )
    denied_disable = client.patch(
        f"/api/users/{admin['id']}/disabled",
        headers=admin_headers,
        json={"disabled": True},
    )
    denied_revoke = client.post(
        f"/api/users/{admin['id']}/revoke",
        headers=admin_headers,
    )

    assert denied_create.status_code == 403
    assert denied_disable.status_code == 403
    assert denied_revoke.status_code == 403
    assert runtime.users.get_by_username("forbidden-admin") is None
    assert runtime.users.get_by_id(admin["id"]).disabled is False
    assert runtime.auth_audit.list() == audit_before


def test_root_identity_is_protected_from_account_management_apis(
    client: TestClient,
    runtime: AuthRuntime,
):
    root = _root(runtime)
    headers = _headers(client, "ai360", _ROOT_PASSWORD)
    original = runtime.users.get_by_id(root.id)

    responses = (
        client.post(
            "/api/users",
            headers=headers,
            json={
                "username": "second-root",
                "password": _ROOT_PASSWORD,
                "role": "root",
            },
        ),
        client.patch(
            f"/api/users/{root.id}/disabled",
            headers=headers,
            json={"disabled": True},
        ),
        client.delete(f"/api/users/{root.id}", headers=headers),
        client.patch(
            f"/api/users/{root.id}/role",
            headers=headers,
            json={"role": "admin"},
        ),
        client.post(
            f"/api/users/{root.id}/password-reset",
            headers=headers,
            json={"password": _NEW_PASSWORD},
        ),
    )

    assert [response.status_code for response in responses] == [403] * 5
    assert runtime.users.get_by_id(root.id) == original
    assert [user.role for user in runtime.users.list()] == [AccountRole.ROOT]


def test_server_revalidation_rejects_stale_pre_migration_root_claim(
    client: TestClient,
    runtime: AuthRuntime,
):
    root = _root(runtime)
    stale_admin_claim = replace(
        root,
        role=AccountRole.ADMIN,
        token_version=max(0, root.token_version - 1),
    )
    stale_token = runtime.tokens.issue(stale_admin_claim)

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {stale_token}"},
    )

    assert response.status_code == 401


def test_role_promotion_and_demotion_update_access_and_sessions_atomically(
    client: TestClient,
    runtime: AuthRuntime,
):
    root = _root(runtime)
    admin = _create_admin(runtime, root.id)
    access = _register_scoped_resources(runtime)
    user = runtime.users.create(
        username="scoped-user",
        password_hash=hash_password(_USER_PASSWORD),
        role=AccountRole.USER,
        created_by=root.id,
        grants=[
            (ResourceType.PROJECT, "project-a"),
            (ResourceType.AVATAR_CHARACTER, "character-a"),
            (ResourceType.CUSTOM_VOICE, "voice-a"),
        ],
        defaults=("project-a", "character-a", "indextts", "voice-a"),
    )
    runtime.resources.register(
        resource_type=ResourceType.PROJECT,
        resource_id="owned-project",
        owner_user_id=user.id,
        visibility=ResourceVisibility.PRIVATE,
    )
    root_headers = _headers(client, "ai360", _ROOT_PASSWORD)
    old_user_headers = _headers(client, "scoped-user", _USER_PASSWORD)

    promoted = client.patch(
        f"/api/users/{user.id}/role",
        headers=root_headers,
        json={"role": "admin"},
    )

    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"
    assert promoted.json()["grants"] is None
    assert promoted.json()["defaults"] is None
    assert runtime.account_access.list_grants(user.id) == ()
    assert runtime.account_access.get_defaults(user.id) is None
    assert runtime.resources.list_owned(user.id)[0].resource_id == "owned-project"
    assert client.get("/api/auth/me", headers=old_user_headers).status_code == 401

    old_admin_headers = _headers(client, "admin", _ADMIN_PASSWORD)
    token_version = runtime.users.get_by_id(admin.id).token_version
    invalid = client.patch(
        f"/api/users/{admin.id}/role",
        headers=root_headers,
        json={"role": "user"},
    )
    assert invalid.status_code == 422
    unchanged = runtime.users.get_by_id(admin.id)
    assert unchanged.role is AccountRole.ADMIN
    assert unchanged.token_version == token_version
    assert client.get("/api/auth/me", headers=old_admin_headers).status_code == 200

    demoted = client.patch(
        f"/api/users/{admin.id}/role",
        headers=root_headers,
        json={"role": "user", "access": access},
    )
    assert demoted.status_code == 200
    assert demoted.json()["role"] == "user"
    assert demoted.json()["grants"] == access["grants"]
    assert demoted.json()["defaults"] == access["defaults"]
    assert client.get("/api/auth/me", headers=old_admin_headers).status_code == 401


def test_password_reset_never_returns_or_audits_secrets_and_revokes_sessions(
    client: TestClient,
    runtime: AuthRuntime,
    caplog: pytest.LogCaptureFixture,
):
    root = _root(runtime)
    admin = _create_admin(runtime, root.id)
    user = _create_user(runtime, admin.id)
    root_headers = _headers(client, "ai360", _ROOT_PASSWORD)
    admin_headers = _headers(client, "admin", _ADMIN_PASSWORD)
    old_user_headers = _headers(client, "user", _USER_PASSWORD)
    original = runtime.users.get_by_id(user.id)

    denied = client.post(
        f"/api/users/{user.id}/password-reset",
        headers=admin_headers,
        json={"password": _NEW_PASSWORD},
    )
    assert denied.status_code == 403
    assert runtime.users.get_by_id(user.id) == original

    response = client.post(
        f"/api/users/{user.id}/password-reset",
        headers=root_headers,
        json={"password": _NEW_PASSWORD},
    )

    assert response.status_code == 200
    payload_text = response.text.casefold()
    assert _NEW_PASSWORD not in response.text
    assert "password" not in payload_text
    assert "hash" not in payload_text
    updated = runtime.users.get_by_id(user.id)
    assert updated.password_hash != original.password_hash
    assert updated.password_hash != _NEW_PASSWORD
    assert verify_password(_NEW_PASSWORD, updated.password_hash) is True
    assert updated.token_version == original.token_version + 1
    assert client.get("/api/auth/me", headers=old_user_headers).status_code == 401

    audit = runtime.auth_audit.list()
    reset_event = audit[-1]
    assert reset_event.action == "account_password_reset"
    assert reset_event.actor_user_id == root.id
    assert reset_event.target_user_id == user.id
    audit_text = json.dumps(
        [asdict(event) for event in audit],
        default=str,
    ).casefold()
    assert _NEW_PASSWORD not in audit_text
    for forbidden in ("password_hash", "jwt", "credential", "token"):
        assert forbidden not in audit_text
    assert _NEW_PASSWORD not in caplog.text


def test_root_owned_resource_safety_blocks_deletion_without_partial_mutation(
    client: TestClient,
    runtime: AuthRuntime,
):
    root = _root(runtime)
    admin = _create_admin(runtime, root.id)
    root_headers = _headers(client, "ai360", _ROOT_PASSWORD)
    runtime.resources.register(
        resource_type=ResourceType.PROJECT,
        resource_id="admin-private-project",
        owner_user_id=admin.id,
        visibility=ResourceVisibility.PRIVATE,
    )
    disabled = client.patch(
        f"/api/users/{admin.id}/disabled",
        headers=root_headers,
        json={"disabled": True},
    )
    assert disabled.status_code == 200
    audit_before = runtime.auth_audit.list()

    blocked = client.delete(f"/api/users/{admin.id}", headers=root_headers)

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["resource_counts"] == {"project": 1}
    assert runtime.users.get_by_id(admin.id) is not None
    assert runtime.auth_audit.list() == audit_before

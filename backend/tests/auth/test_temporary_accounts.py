"""Temporary-account lifecycle, expiry, and grant contract tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.models import (
    AccountRole,
    AccountType,
    ResourceType,
    ResourceVisibility,
)
from app.auth.passwords import hash_password
from app.auth.repositories import (
    InvalidResourceGrantError,
    TemporaryCredentialCreate,
)
from app.auth.resources import list_accessible_resources
from app.auth.routes import (
    auth_router,
    temporary_accounts_router,
    users_router,
)
from app.auth.runtime import AuthRuntime, build_auth_runtime, get_auth_runtime
from app.config import TTSRouterConfig

_ADMIN_PASSWORD = "admin-password"


@pytest.fixture()
def runtime(tmp_path: Path) -> AuthRuntime:
    return build_auth_runtime(
        TTSRouterConfig(
            _env_file=None,
            env="dev",
            session_jwt_secret="test-only-session-secret",
            auth_database_path=str(tmp_path / "accounts.db"),
        )
    )


@pytest.fixture()
def client(runtime: AuthRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(temporary_accounts_router)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    return TestClient(app)


def _bootstrap(runtime: AuthRuntime):
    admin = runtime.users.create(
        username="admin",
        password_hash=hash_password(_ADMIN_PASSWORD),
        role=AccountRole.ADMIN,
    )
    resources = (
        (ResourceType.PROJECT, "proj-b85afb8bb6"),
        (ResourceType.PROJECT, "esg-7dea843a0d"),
        (ResourceType.AVATAR_CHARACTER, "0713"),
        (ResourceType.CUSTOM_VOICE, "hayley"),
    )
    for resource_type, resource_id in resources:
        runtime.resources.register(
            resource_type=resource_type,
            resource_id=resource_id,
            owner_user_id=None,
            visibility=ResourceVisibility.SYSTEM_PUBLIC,
        )
    return admin


def _admin_headers(client: TestClient) -> dict[str, str]:
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": _ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _batch_body() -> dict[str, object]:
    return {
        "grants": {
            "projects": ["proj-b85afb8bb6"],
            "avatar_characters": ["0713"],
            "custom_voices": ["hayley"],
        },
        "defaults": {
            "project_id": "proj-b85afb8bb6",
            "character_id": "0713",
            "voice_provider": "indextts",
            "voice_id": "hayley",
        },
    }


def test_batch_creates_exactly_five_one_time_plaintext_passwords(
    client: TestClient,
    runtime: AuthRuntime,
):
    _bootstrap(runtime)
    response = client.post(
        "/api/temporary-accounts/batches",
        headers=_admin_headers(client),
        json=_batch_body(),
    )

    assert response.status_code == 201
    payload = response.json()
    credentials = payload["credentials"]
    assert len(credentials) == 5
    assert len({item["password"] for item in credentials}) == 5
    assert all(
        len(item["password"]) == 12 and item["password"].isascii()
        and item["password"].isalnum()
        for item in credentials
    )
    assert all(item["expires_at"] is None for item in credentials)

    passwords = {item["password"] for item in credentials}
    with runtime.database.transaction() as connection:
        rows = connection.execute(
            """
            SELECT users.username, users.password_hash,
                   temporary_credentials.code_locator
            FROM temporary_credentials
            INNER JOIN users ON users.id = temporary_credentials.user_id
            """
        ).fetchall()
    assert len(rows) == 5
    persisted_values = {str(value) for row in rows for value in tuple(row)}
    assert passwords.isdisjoint(persisted_values)

    audit = client.get(
        "/api/temporary-accounts/batches",
        headers=_admin_headers(client),
    )
    assert audit.status_code == 200
    audit_text = audit.text
    assert "password_hash" not in audit_text
    assert all(password not in audit_text for password in passwords)


def test_first_login_starts_one_hard_window_and_revoke_ends_access(
    client: TestClient,
    runtime: AuthRuntime,
):
    _bootstrap(runtime)
    headers = _admin_headers(client)
    created = client.post(
        "/api/temporary-accounts/batches",
        headers=headers,
        json=_batch_body(),
    ).json()
    password = created["credentials"][0]["password"]
    user_id = created["credentials"][0]["user_id"]
    user = runtime.users.get_by_id(user_id)
    assert user is not None

    formal_login = client.post(
        "/api/auth/login",
        json={"username": user.username, "password": password},
    )
    assert formal_login.status_code == 401

    first = client.post(
        "/api/auth/temporary-login",
        json={"password": password},
    )
    second = client.post(
        "/api/auth/temporary-login",
        json={"password": password},
    )
    assert first.status_code == second.status_code == 200
    first_account = first.json()["account"]
    second_account = second.json()["account"]
    assert first_account["kind"] == AccountType.TEMPORARY.value
    assert first_account["expires_at"] == second_account["expires_at"]
    assert 0 < first_account["remaining_seconds"] <= 72 * 60 * 60
    assert first_account["defaults"] == _batch_body()["defaults"]

    claims = runtime.tokens.decode(first.json()["token"])
    hard_expiry = datetime.fromisoformat(first_account["expires_at"])
    assert claims.account_type is AccountType.TEMPORARY
    assert claims.expires_at <= int(hard_expiry.timestamp())

    bearer = {"Authorization": f"Bearer {first.json()['token']}"}
    current = client.get("/api/auth/me", headers=bearer)
    assert current.status_code == 200
    assert current.json()["expires_at"] == first_account["expires_at"]

    revoked = client.post(
        f"/api/temporary-accounts/batches/{created['batch_id']}/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["state"] == "revoked"
    assert client.get("/api/auth/me", headers=bearer).status_code == 401
    assert (
        client.post(
            "/api/auth/temporary-login",
            json={"password": password},
        ).status_code
        == 401
    )


def test_expired_temporary_credential_is_revalidated_on_every_request(
    client: TestClient,
    runtime: AuthRuntime,
):
    _bootstrap(runtime)
    created = client.post(
        "/api/temporary-accounts/batches",
        headers=_admin_headers(client),
        json=_batch_body(),
    ).json()
    password = created["credentials"][0]["password"]
    login = client.post(
        "/api/auth/temporary-login",
        json={"password": password},
    )
    assert login.status_code == 200

    expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with runtime.database.transaction(write=True) as connection:
        connection.execute(
            """
            UPDATE temporary_credentials SET expires_at = ? WHERE user_id = ?
            """,
            (expired_at.isoformat(), created["credentials"][0]["user_id"]),
        )

    bearer = {"Authorization": f"Bearer {login.json()['token']}"}
    assert client.get("/api/auth/me", headers=bearer).status_code == 401
    assert (
        client.post(
            "/api/auth/temporary-login",
            json={"password": password},
        ).status_code
        == 401
    )


def test_concurrent_activation_keeps_the_first_expiry(runtime: AuthRuntime):
    admin = _bootstrap(runtime)
    password = "A00xPass0000"  # gitleaks:allow
    batch = runtime.temporary_accounts.create_batch(
        created_by=admin.id,
        credentials=[
            TemporaryCredentialCreate(
                locator=f"A0{index}x",
                password_hash=hash_password(
                    f"A0{index}xPass{index:04d}"  # gitleaks:allow
                ),
            )
            for index in range(5)
        ],
        grants=[
            (ResourceType.PROJECT, "proj-b85afb8bb6"),
            (ResourceType.AVATAR_CHARACTER, "0713"),
            (ResourceType.CUSTOM_VOICE, "hayley"),
        ],
        defaults=("proj-b85afb8bb6", "0713", "indextts", "hayley"),
        duration_seconds=72 * 60 * 60,
    )
    user_id = batch.accounts[0].user.id
    start = datetime.now(timezone.utc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda value: runtime.temporary_accounts.activate(
                    user_id=user_id,
                    now=value,
                )[1],
                (start, start + timedelta(seconds=1)),
            )
        )

    assert results[0].first_used_at == results[1].first_used_at
    assert results[0].expires_at == results[1].expires_at
    assert password not in {account.user.password_hash for account in batch.accounts}


def test_invalid_default_rolls_back_entire_batch(runtime: AuthRuntime):
    admin = _bootstrap(runtime)
    with pytest.raises(InvalidResourceGrantError):
        runtime.temporary_accounts.create_batch(
            created_by=admin.id,
            credentials=[
                TemporaryCredentialCreate(
                    locator=f"abcdef0{index}",
                    password_hash="hash",
                )
                for index in range(5)
            ],
            grants=[
                (ResourceType.PROJECT, "proj-b85afb8bb6"),
                (ResourceType.AVATAR_CHARACTER, "0713"),
                (ResourceType.CUSTOM_VOICE, "hayley"),
            ],
            defaults=("esg-7dea843a0d", "0713", "indextts", "hayley"),
            duration_seconds=72 * 60 * 60,
        )

    assert runtime.temporary_accounts.list_batches() == []


def test_temporary_resource_list_contains_only_explicit_grants(
    runtime: AuthRuntime,
):
    admin = _bootstrap(runtime)
    batch = runtime.temporary_accounts.create_batch(
        created_by=admin.id,
        credentials=[
            TemporaryCredentialCreate(
                locator=f"fedcba0{index}",
                password_hash="hash",
            )
            for index in range(5)
        ],
        grants=[
            (ResourceType.PROJECT, "proj-b85afb8bb6"),
            (ResourceType.AVATAR_CHARACTER, "0713"),
            (ResourceType.CUSTOM_VOICE, "hayley"),
        ],
        defaults=("proj-b85afb8bb6", "0713", "indextts", "hayley"),
        duration_seconds=72 * 60 * 60,
    )
    temporary_user = batch.accounts[0].user

    project_ids = {
        item.resource_id
        for item in list_accessible_resources(
            runtime.resources,
            temporary_user,
            ResourceType.PROJECT,
        )
    }
    assert project_ids == {"proj-b85afb8bb6"}

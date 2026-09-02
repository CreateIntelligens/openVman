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
_ROOT_PASSWORD = "root-password"


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
        "/api/v1/auth/login",
        json={"username": "admin", "password": _ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _root_headers(client: TestClient) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "ai360", "password": _ROOT_PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _batch_body() -> dict[str, object]:
    return {
        "grants": {
            "projects": ["proj-b85afb8bb6"],
            "avatar_characters": ["0713"],
            "custom_voices": ["hayley"],
            "avatar_mascots": [],
            "avatar_backgrounds": [],
        },
        "defaults": {
            "project_id": "proj-b85afb8bb6",
            "character_id": "0713",
            "voice_provider": "indextts",
            "voice_id": "hayley",
            "mascot_id": "",
            "background_id": "",
        },
    }


def test_batch_creates_exactly_five_one_time_plaintext_passwords(
    client: TestClient,
    runtime: AuthRuntime,
):
    _bootstrap(runtime)
    response = client.post(
        "/api/v1/temporary-accounts/batches",
        headers=_admin_headers(client),
        json=_batch_body(),
    )

    assert response.status_code == 201
    payload = response.json()
    credentials = payload["credentials"]
    assert len(credentials) == 5
    assert len({item["password"] for item in credentials}) == 5
    assert all(
        len(item["password"]) == 20 and item["password"].isascii()
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
    locators = {password[:12] for password in passwords}
    assert {row["code_locator"] for row in rows} == locators
    assert all(row["username"] not in passwords for row in rows)
    assert all(row["username"] not in locators for row in rows)

    audit = client.get(
        "/api/v1/temporary-accounts/batches",
        headers=_admin_headers(client),
    )
    assert audit.status_code == 200
    audit_text = audit.text
    assert "password_hash" not in audit_text
    assert all(password not in audit_text for password in passwords)
    assert all(locator not in audit_text for locator in locators)


def test_temporary_batch_admin_portal_access_is_explicit_and_revocable(
    client: TestClient,
    runtime: AuthRuntime,
):
    _bootstrap(runtime)
    admin_headers = _admin_headers(client)
    created = client.post(
        "/api/v1/temporary-accounts/batches",
        headers=admin_headers,
        json=_batch_body(),
    ).json()
    password = created["credentials"][0]["password"]

    assert created["admin_portal_access"] is False
    denied = client.post(
        "/api/v1/auth/admin-temporary-login",
        json={"password": password},
    )
    assert denied.status_code == 403
    with runtime.database.transaction() as connection:
        first_used_at = connection.execute(
            """
            SELECT first_used_at FROM temporary_credentials
            WHERE batch_id = ? ORDER BY user_id LIMIT 1
            """,
            (created["batch_id"],),
        ).fetchone()["first_used_at"]
    assert first_used_at is None

    granted = client.patch(
        f"/api/v1/temporary-accounts/batches/{created['batch_id']}"
        "/admin-portal-access",
        headers=admin_headers,
        json={"enabled": True},
    )
    assert granted.status_code == 200
    assert granted.json()["admin_portal_access"] is True
    assert all(
        account["admin_portal_access"] is True
        for account in granted.json()["accounts"]
    )

    portal_login = client.post(
        "/api/v1/auth/admin-temporary-login",
        json={"password": password},
    )
    assert portal_login.status_code == 200
    portal_headers = {
        "Authorization": f"Bearer {portal_login.json()['token']}",
    }
    assert client.get("/api/v1/auth/admin-me", headers=portal_headers).status_code == 200

    revoked = client.patch(
        f"/api/v1/temporary-accounts/batches/{created['batch_id']}"
        "/admin-portal-access",
        headers=admin_headers,
        json={"enabled": False},
    )
    assert revoked.status_code == 200
    assert revoked.json()["admin_portal_access"] is False
    assert client.get("/api/v1/auth/me", headers=portal_headers).status_code == 401

    normal_login = client.post(
        "/api/v1/auth/temporary-login",
        json={"password": password},
    )
    assert normal_login.status_code == 200
    normal_headers = {
        "Authorization": f"Bearer {normal_login.json()['token']}",
    }
    assert client.get("/api/v1/auth/me", headers=normal_headers).status_code == 200
    assert client.get("/api/v1/auth/admin-me", headers=normal_headers).status_code == 403


@pytest.mark.parametrize("actor_role", [AccountRole.ROOT, AccountRole.ADMIN])
def test_root_and_admin_batch_audit_and_revoke_never_reveal_credentials(
    client: TestClient,
    runtime: AuthRuntime,
    actor_role: AccountRole,
):
    actor = _bootstrap(runtime) if actor_role is AccountRole.ADMIN else None
    if actor_role is AccountRole.ROOT:
        actor = runtime.users.create_root(
            username="ai360",
            password_hash=hash_password(_ROOT_PASSWORD),
        )
        for resource_type, resource_id in (
            (ResourceType.PROJECT, "proj-b85afb8bb6"),
            (ResourceType.PROJECT, "esg-7dea843a0d"),
            (ResourceType.AVATAR_CHARACTER, "0713"),
            (ResourceType.CUSTOM_VOICE, "hayley"),
        ):
            runtime.resources.register(
                resource_type=resource_type,
                resource_id=resource_id,
                owner_user_id=None,
                visibility=ResourceVisibility.SYSTEM_PUBLIC,
            )
    headers = (
        _root_headers(client)
        if actor_role is AccountRole.ROOT
        else _admin_headers(client)
    )
    created_response = client.post(
        "/api/v1/temporary-accounts/batches",
        headers=headers,
        json=_batch_body(),
    )
    assert created_response.status_code == 201
    created = created_response.json()
    plaintext_credentials = {
        item["password"] for item in created["credentials"]
    }
    with runtime.database.transaction() as connection:
        persisted_locators = {
            row["code_locator"]
            for row in connection.execute(
                """
                SELECT code_locator FROM temporary_credentials
                WHERE batch_id = ?
                """,
                (created["batch_id"],),
            ).fetchall()
        }

    listed = client.get("/api/v1/temporary-accounts/batches", headers=headers)
    assert listed.status_code == 200
    listed_text = listed.text
    assert "password" not in listed_text.casefold()
    assert "hash" not in listed_text.casefold()
    assert all(secret not in listed_text for secret in plaintext_credentials)
    assert all(locator not in listed_text for locator in persisted_locators)

    revoked = client.post(
        f"/api/v1/temporary-accounts/batches/{created['batch_id']}/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["state"] == "revoked"
    assert "password" not in revoked.text.casefold()
    assert all(secret not in revoked.text for secret in plaintext_credentials)
    assert all(locator not in revoked.text for locator in persisted_locators)

    events = runtime.auth_audit.list()
    assert [event.action for event in events[-2:]] == [
        "temporary_batch_created",
        "temporary_batch_revoked",
    ]
    assert all(event.actor_user_id == actor.id for event in events[-2:])
    audit_text = " ".join(event.metadata_json for event in events)
    assert all(secret not in audit_text for secret in plaintext_credentials)
    assert all(locator not in audit_text for locator in persisted_locators)


def test_first_login_starts_one_hard_window_and_revoke_ends_access(
    client: TestClient,
    runtime: AuthRuntime,
):
    _bootstrap(runtime)
    headers = _admin_headers(client)
    created = client.post(
        "/api/v1/temporary-accounts/batches",
        headers=headers,
        json=_batch_body(),
    ).json()
    password = created["credentials"][0]["password"]
    user_id = created["credentials"][0]["user_id"]
    user = runtime.users.get_by_id(user_id)
    assert user is not None

    formal_login = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": password},
    )
    assert formal_login.status_code == 401

    first = client.post(
        "/api/v1/auth/temporary-login",
        json={"password": password},
    )
    second = client.post(
        "/api/v1/auth/temporary-login",
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
    current = client.get("/api/v1/auth/me", headers=bearer)
    assert current.status_code == 200
    assert current.json()["expires_at"] == first_account["expires_at"]

    revoked = client.post(
        f"/api/v1/temporary-accounts/batches/{created['batch_id']}/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["state"] == "revoked"
    assert client.get("/api/v1/auth/me", headers=bearer).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/temporary-login",
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
        "/api/v1/temporary-accounts/batches",
        headers=_admin_headers(client),
        json=_batch_body(),
    ).json()
    password = created["credentials"][0]["password"]
    login = client.post(
        "/api/v1/auth/temporary-login",
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
    assert client.get("/api/v1/auth/me", headers=bearer).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/temporary-login",
            json={"password": password},
        ).status_code
        == 401
    )


def test_legacy_locator_username_is_scrubbed_without_breaking_legacy_login(
    client: TestClient,
    runtime: AuthRuntime,
):
    admin = _bootstrap(runtime)
    legacy_password = "LegacyPwd001"  # gitleaks:allow
    credentials = [
        TemporaryCredentialCreate(
            locator=(legacy_password if index == 0 else f"OtherPwd{index:04d}"),
            password_hash=(
                hash_password(legacy_password) if index == 0 else "unused-hash"
            ),
        )
        for index in range(5)
    ]
    batch = runtime.temporary_accounts.create_batch(
        created_by=admin.id,
        credentials=credentials,
        grants=[
            (ResourceType.PROJECT, "proj-b85afb8bb6"),
            (ResourceType.AVATAR_CHARACTER, "0713"),
            (ResourceType.CUSTOM_VOICE, "hayley"),
        ],
        defaults=("proj-b85afb8bb6", "0713", "indextts", "hayley"),
        duration_seconds=72 * 60 * 60,
    )
    with runtime.database.transaction(write=True) as connection:
        connection.execute(
            """
            UPDATE users
            SET username = (
                    SELECT code_locator FROM temporary_credentials
                    WHERE temporary_credentials.user_id = users.id
                ),
                -- 真實寫入會小寫化，模擬舊資料時必須跟著小寫，
                -- 否則遷移條件在測試裡會意外成立。
                username_normalized = (
                    SELECT lower(code_locator) FROM temporary_credentials
                    WHERE temporary_credentials.user_id = users.id
                )
            WHERE id IN (
                SELECT user_id FROM temporary_credentials WHERE batch_id = ?
            )
            """,
            (batch.batch.id,),
        )
        connection.execute("DELETE FROM schema_migrations WHERE version >= 5")

    runtime.database.initialize()

    with runtime.database.transaction() as connection:
        rows = connection.execute(
            """
            SELECT users.username, users.username_normalized,
                   temporary_credentials.code_locator
            FROM temporary_credentials
            INNER JOIN users ON users.id = temporary_credentials.user_id
            WHERE temporary_credentials.batch_id = ?
            ORDER BY users.id
            """,
            (batch.batch.id,),
        ).fetchall()
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert all(row["username"].startswith("tmp-") for row in rows)
    assert all(row["username"] != row["code_locator"] for row in rows)
    assert all(row["username_normalized"] != row["code_locator"] for row in rows)
    # 測試刻意移除舊的遷移紀錄再重跑，所以會補回 v6 與後續 migration。
    assert [row["version"] for row in versions] == [1, 2, 3, 4, 6, 7]
    assert violations == []

    login = client.post(
        "/api/v1/auth/temporary-login",
        json={"password": legacy_password},
    )
    assert login.status_code == 200
    assert login.json()["account"]["username"].startswith("tmp-")
    assert legacy_password not in login.text


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

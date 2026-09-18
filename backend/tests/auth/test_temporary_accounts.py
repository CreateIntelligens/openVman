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


def test_batch_creates_five_recoverable_passwords_without_storage_leaks(
    client: TestClient,
    runtime: AuthRuntime,
    caplog: pytest.LogCaptureFixture,
):
    _bootstrap(runtime)
    response = client.post(
        "/api/v1/temporary-accounts/batches",
        headers=_admin_headers(client),
        json=_batch_body(),
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
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
                   temporary_credentials.code_locator,
                   temporary_credentials.password_ciphertext
            FROM temporary_credentials
            INNER JOIN users ON users.id = temporary_credentials.user_id
            """
        ).fetchall()
        database_dump = "\n".join(connection.iterdump())
    assert len(rows) == 5
    locators = {password[:12] for password in passwords}
    assert {row["code_locator"] for row in rows} == locators
    assert all(row["username"] not in passwords for row in rows)
    assert all(row["username"] not in locators for row in rows)
    assert all(row["password_hash"].startswith("$2") for row in rows)
    assert all(row["password_ciphertext"] for row in rows)
    assert all(password not in database_dump for password in passwords)

    audit = client.get(
        "/api/v1/temporary-accounts/batches",
        headers=_admin_headers(client),
    )
    assert audit.status_code == 200
    assert audit.headers["cache-control"] == "no-store"
    assert {
        account["user_id"]: account["password"]
        for account in audit.json()[0]["accounts"]
    } == {item["user_id"]: item["password"] for item in credentials}
    for field in ("password_hash", "password_ciphertext", "code_locator"):
        assert field not in response.text
        assert field not in audit.text
    for row in rows:
        assert row["password_hash"] not in audit.text
        assert row["password_ciphertext"] not in audit.text
    assert all(password not in caplog.text for password in passwords)


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
    assert granted.headers["cache-control"] == "no-store"
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
def test_root_and_admin_recover_passwords_without_audit_or_storage_leaks(
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
    assert listed.headers["cache-control"] == "no-store"
    assert {
        account["password"] for account in listed.json()[0]["accounts"]
    } == plaintext_credentials
    for field in ("password_hash", "password_ciphertext", "code_locator"):
        assert field not in listed_text

    revoked = client.post(
        f"/api/v1/temporary-accounts/batches/{created['batch_id']}/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["state"] == "revoked"
    assert revoked.headers["cache-control"] == "no-store"
    for field in ("password_hash", "password_ciphertext", "code_locator"):
        assert field not in revoked.text

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
        connection.execute(
            "ALTER TABLE temporary_credentials DROP COLUMN password_ciphertext",
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
    # 不寫死完整清單：那會讓每一個新 migration 都弄壞這個與它無關的測試。
    applied = [row["version"] for row in versions]
    assert applied == sorted(applied)
    assert 5 not in applied, "被移除的 v5 不該補回來"
    assert {1, 2, 3, 4, 6}.issubset(applied)
    assert violations == []
    listed = client.get(
        "/api/v1/temporary-accounts/batches", headers=_admin_headers(client),
    )
    assert listed.status_code == 200
    assert all(
        account["password"] is None
        for account in listed.json()[0]["accounts"]
    )

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


@pytest.mark.parametrize("dedicated_secret", [None, "dedicated-key-" * 4])
def test_passwords_survive_a_fresh_runtime(
    runtime: AuthRuntime,
    dedicated_secret: str | None,
):
    config = runtime.config.model_copy(
        update={"auth_temporary_password_secret": dedicated_secret},
    )
    original_runtime = build_auth_runtime(config)
    _bootstrap(original_runtime)
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(temporary_accounts_router)
    app.dependency_overrides[get_auth_runtime] = lambda: original_runtime
    with TestClient(app) as original_client:
        created = original_client.post(
            "/api/v1/temporary-accounts/batches",
            headers=_admin_headers(original_client),
            json=_batch_body(),
        )
        assert created.status_code == 201
        expected = {
            item["user_id"]: item["password"]
            for item in created.json()["credentials"]
        }

    # 專用金鑰存在時，輪替 session 金鑰不應使已存密碼失效。
    if dedicated_secret is not None:
        config = config.model_copy(
            update={"session_jwt_secret": "new-session-signing-key-" * 3},
        )
    restarted_runtime = build_auth_runtime(config)
    app.dependency_overrides[get_auth_runtime] = lambda: restarted_runtime
    with TestClient(app) as restarted_client:
        listed = restarted_client.get(
            "/api/v1/temporary-accounts/batches",
            headers=_admin_headers(restarted_client),
        )
        assert listed.status_code == 200
        assert listed.headers["cache-control"] == "no-store"
        assert {
            item["user_id"]: item["password"]
            for item in listed.json()[0]["accounts"]
        } == expected
        password = next(iter(expected.values()))
        assert restarted_client.post(
            "/api/v1/auth/temporary-login", json={"password": password},
        ).status_code == 200


@pytest.mark.parametrize("failure", ["legacy-null", "corrupt", "wrong-key"])
def test_unrecoverable_password_is_null_and_does_not_break_login(
    client: TestClient,
    runtime: AuthRuntime,
    failure: str,
    caplog: pytest.LogCaptureFixture,
):
    _bootstrap(runtime)
    headers = _admin_headers(client)
    created = client.post(
        "/api/v1/temporary-accounts/batches",
        headers=headers,
        json=_batch_body(),
    ).json()
    credential = created["credentials"][0]
    if failure == "wrong-key":
        runtime = build_auth_runtime(
            runtime.config.model_copy(
                update={"auth_temporary_password_secret": "other-key-" * 5},
            ),
        )
        client.app.dependency_overrides[get_auth_runtime] = lambda: runtime
    else:
        with runtime.database.transaction(write=True) as connection:
            connection.execute(
                """
                UPDATE temporary_credentials SET password_ciphertext = ?
                WHERE user_id = ?
                """,
                (
                    None if failure == "legacy-null" else "invalid-ciphertext",
                    credential["user_id"],
                ),
            )

    listed = client.get("/api/v1/temporary-accounts/batches", headers=headers)
    assert listed.status_code == 200
    account = next(
        item for item in listed.json()[0]["accounts"]
        if item["user_id"] == credential["user_id"]
    )
    assert "password" in account
    assert account["password"] is None
    assert client.post(
        "/api/v1/auth/temporary-login",
        json={"password": credential["password"]},
    ).status_code == 200
    assert credential["password"] not in caplog.text


@pytest.mark.parametrize("actor", ["anonymous", "user", "temporary"])
def test_batch_passwords_require_admin_even_with_portal_access(
    client: TestClient,
    runtime: AuthRuntime,
    actor: str,
):
    _bootstrap(runtime)
    created = client.post(
        "/api/v1/temporary-accounts/batches",
        headers=_admin_headers(client),
        json={**_batch_body(), "admin_portal_access": True},
    ).json()
    passwords = [item["password"] for item in created["credentials"]]
    client.cookies.clear()
    headers = {}
    if actor == "user":
        runtime.users.create(
            username="portal-user",
            password_hash=hash_password("portal-user-password"),
            role=AccountRole.USER,
            admin_portal_access=True,
        )
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "portal-user", "password": "portal-user-password"},
        )
    elif actor == "temporary":
        login = client.post(
            "/api/v1/auth/admin-temporary-login",
            json={"password": passwords[0]},
        )
    if actor != "anonymous":
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        assert client.get(
            "/api/v1/auth/admin-me", headers=headers,
        ).status_code == 200

    denied = client.get("/api/v1/temporary-accounts/batches", headers=headers)
    assert denied.status_code == (401 if actor == "anonymous" else 403)
    assert all(password not in denied.text for password in passwords)


def _login_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_temporary_batches_are_scoped_to_the_creators_subtree(
    client: TestClient,
    runtime: AuthRuntime,
):
    """平行 admin 不得看見或管理彼此及 ROOT 發出的臨時批次。

    線上發現：受限 admin 登入後看到 ROOT 發的 16 批臨時帳號，且能撤銷。
    """
    root = runtime.users.create_root(
        username="ai360",
        password_hash=hash_password(_ROOT_PASSWORD),
    )
    for resource_type, resource_id in (
        (ResourceType.PROJECT, "proj-b85afb8bb6"),
        (ResourceType.AVATAR_CHARACTER, "0713"),
        (ResourceType.CUSTOM_VOICE, "hayley"),
    ):
        runtime.resources.register(
            resource_type=resource_type,
            resource_id=resource_id,
            owner_user_id=None,
            visibility=ResourceVisibility.SYSTEM_PUBLIC,
        )
    runtime.users.create(
        username="admin",
        password_hash=hash_password(_ADMIN_PASSWORD),
        role=AccountRole.ADMIN,
        created_by=root.id,
    )
    runtime.users.create(
        username="other",
        password_hash=hash_password(_ADMIN_PASSWORD),
        role=AccountRole.ADMIN,
        created_by=root.id,
    )
    root_headers = _root_headers(client)
    admin_headers = _admin_headers(client)
    other_headers = _login_headers(client, "other", _ADMIN_PASSWORD)

    root_batch = client.post(
        "/api/v1/temporary-accounts/batches",
        headers=root_headers, json=_batch_body(),
    ).json()["batch_id"]
    admin_batch = client.post(
        "/api/v1/temporary-accounts/batches",
        headers=admin_headers, json=_batch_body(),
    ).json()["batch_id"]

    def visible(headers: dict[str, str]) -> set[str]:
        response = client.get(
            "/api/v1/temporary-accounts/batches", headers=headers,
        )
        assert response.status_code == 200
        return {batch["batch_id"] for batch in response.json()}

    assert visible(root_headers) == {root_batch, admin_batch}
    assert visible(admin_headers) == {admin_batch}
    assert visible(other_headers) == set()

    # 別人的批次一律當不存在。
    for path in (
        f"/api/v1/temporary-accounts/batches/{root_batch}/revoke",
        f"/api/v1/temporary-accounts/batches/{admin_batch}/revoke",
    ):
        assert client.post(path, headers=other_headers).status_code == 404
    denied = client.patch(
        f"/api/v1/temporary-accounts/batches/{root_batch}/admin-portal-access",
        headers=admin_headers, json={"enabled": True},
    )
    assert denied.status_code == 404
    root_batch_details = runtime.temporary_accounts.get_batch(root_batch)
    assert root_batch_details is not None
    assert root_batch_details.batch.revoked_at is None

    # 自己的批次照常，ROOT 動任何批次都行。
    assert client.post(
        f"/api/v1/temporary-accounts/batches/{admin_batch}/revoke",
        headers=admin_headers,
    ).status_code == 200
    assert client.post(
        f"/api/v1/temporary-accounts/batches/{root_batch}/revoke",
        headers=root_headers,
    ).status_code == 200


@pytest.mark.parametrize("manager", ["creator", "root"])
def test_descendant_batch_is_visible_but_only_creator_or_root_can_manage(
    client: TestClient,
    runtime: AuthRuntime,
    manager: str,
):
    root = runtime.users.create_root(
        username="ai360",
        password_hash=hash_password(_ROOT_PASSWORD),
    )
    root_headers = _root_headers(client)
    for resource_type, resource_id in (
        (ResourceType.PROJECT, "proj-b85afb8bb6"),
        (ResourceType.AVATAR_CHARACTER, "0713"),
        (ResourceType.CUSTOM_VOICE, "hayley"),
    ):
        runtime.resources.register(
            resource_type=resource_type,
            resource_id=resource_id,
            owner_user_id=None,
            visibility=ResourceVisibility.SYSTEM_PUBLIC,
        )

    def create_admin(username: str, headers: dict[str, str]):
        response = client.post(
            "/api/v1/users",
            headers=headers,
            json={
                "username": username,
                "password": _ADMIN_PASSWORD,
                "role": "admin",
            },
        )
        assert response.status_code == 201, response.text
        return response.json(), _login_headers(
            client, username, _ADMIN_PASSWORD,
        )

    admin_a, a_headers = create_admin("admin-a", root_headers)
    admin_b, b_headers = create_admin("admin-b", a_headers)
    sibling, sibling_headers = create_admin("sibling", root_headers)
    assert admin_a["created_by"] == root.id
    assert admin_b["created_by"] == admin_a["id"]
    assert sibling["created_by"] == root.id

    created = client.post(
        "/api/v1/temporary-accounts/batches",
        headers=b_headers,
        json=_batch_body(),
    )
    assert created.status_code == 201, created.text
    batch_id = created.json()["batch_id"]
    path = f"/api/v1/temporary-accounts/batches/{batch_id}"

    for headers in (root_headers, a_headers, b_headers):
        listed = client.get(
            "/api/v1/temporary-accounts/batches", headers=headers,
        )
        assert listed.status_code == 200
        assert {batch["batch_id"] for batch in listed.json()} == {batch_id}
    sibling_list = client.get(
        "/api/v1/temporary-accounts/batches", headers=sibling_headers,
    )
    assert sibling_list.status_code == 200
    assert sibling_list.json() == []

    before = runtime.temporary_accounts.get_batch(batch_id)
    assert before is not None
    assert before.batch.created_by == admin_b["id"]
    audit_before = runtime.auth_audit.list()
    # A 看得到孫節點，但管理權限仍只到直屬，拒絕操作不得改動狀態或審計。
    for headers in (a_headers, sibling_headers):
        assert client.post(
            f"{path}/revoke", headers=headers,
        ).status_code == 404
        assert runtime.temporary_accounts.get_batch(batch_id) == before
        assert runtime.auth_audit.list() == audit_before
        assert client.patch(
            f"{path}/admin-portal-access",
            headers=headers,
            json={"enabled": True},
        ).status_code == 404
        assert runtime.temporary_accounts.get_batch(batch_id) == before
        assert runtime.auth_audit.list() == audit_before

    manager_headers = b_headers if manager == "creator" else root_headers
    enabled = client.patch(
        f"{path}/admin-portal-access",
        headers=manager_headers,
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["admin_portal_access"] is True
    after_toggle = runtime.temporary_accounts.get_batch(batch_id)
    assert after_toggle is not None
    assert all(
        account.user.admin_portal_access for account in after_toggle.accounts
    )
    assert all(
        current.user.token_version == previous.user.token_version + 1
        for previous, current in zip(before.accounts, after_toggle.accounts)
    )

    revoked = client.post(f"{path}/revoke", headers=manager_headers)
    assert revoked.status_code == 200
    assert revoked.json()["state"] == "revoked"
    after_revoke = runtime.temporary_accounts.get_batch(batch_id)
    assert after_revoke is not None
    assert after_revoke.batch.revoked_at is not None
    assert all(account.user.disabled for account in after_revoke.accounts)
    assert all(
        current.user.token_version == previous.user.token_version + 1
        for previous, current in zip(after_toggle.accounts, after_revoke.accounts)
    )

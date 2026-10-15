"""Last-login tracking for account cleanup in the admin account list."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.database import AuthDatabase
from app.auth.models import AccountRole, ResourceType, ResourceVisibility
from app.auth.passwords import hash_password
from app.auth.routes import auth_router, temporary_accounts_router, users_router
from app.auth.runtime import AuthRuntime, build_auth_runtime, get_auth_runtime
from app.auth.user_repository import UserRepository
from app.config import TTSRouterConfig

_ADMIN_PASSWORD = "admin-password"
_USER_PASSWORD = "user-password"


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


def _accounts(runtime: AuthRuntime):
    admin = runtime.users.create(
        username="admin",
        password_hash=hash_password(_ADMIN_PASSWORD),
        role=AccountRole.ADMIN,
    )
    user = runtime.users.create(
        username="viewer",
        password_hash=hash_password(_USER_PASSWORD),
        role=AccountRole.USER,
        created_by=admin.id,
    )
    return admin, user


def _last_login(runtime: AuthRuntime, user_id: str) -> str | None:
    user = runtime.users.get_by_id(user_id)
    assert user is not None
    return user.last_login_at


def _admin_headers(client: TestClient) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": _ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_last_login_column_is_nullable_and_migration_is_rerunnable(
    tmp_path: Path,
):
    database = AuthDatabase(tmp_path / "accounts.db")
    database.initialize()
    users = UserRepository(database)
    existing = users.create(
        username="legacy", password_hash="hash", role=AccountRole.USER,
    )

    # 模擬升級前的資料庫：欄位與遷移紀錄都還不存在。
    with database.transaction(write=True) as connection:
        connection.execute("ALTER TABLE users DROP COLUMN last_login_at")
        connection.execute("DELETE FROM schema_migrations WHERE version = 22")
    database.initialize()
    database.initialize()

    with database.transaction() as connection:
        columns = {
            row["name"]: row
            for row in connection.execute("PRAGMA table_info(users)")
        }
        applied = [
            row["version"]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
    assert columns["last_login_at"]["notnull"] == 0
    assert columns["last_login_at"]["dflt_value"] is None
    assert applied.count(22) == 1
    reloaded = users.get_by_id(existing.id)
    assert reloaded is not None and reloaded.last_login_at is None


def test_migration_records_version_when_column_already_exists(tmp_path: Path):
    database = AuthDatabase(tmp_path / "accounts.db")
    database.initialize()
    with database.transaction(write=True) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 22")

    database.initialize()

    with database.transaction() as connection:
        applied = [
            row["version"]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
    assert applied.count(22) == 1


@pytest.mark.parametrize("endpoint", ["/api/v1/auth/login", "/api/v1/auth/admin-login"])
def test_successful_formal_login_stamps_last_login_without_touching_updated_at(
    client: TestClient,
    runtime: AuthRuntime,
    endpoint: str,
):
    admin, _ = _accounts(runtime)
    assert _last_login(runtime, admin.id) is None

    response = client.post(
        endpoint, json={"username": "admin", "password": _ADMIN_PASSWORD},
    )

    assert response.status_code == 200
    reloaded = runtime.users.get_by_id(admin.id)
    assert reloaded is not None and reloaded.last_login_at is not None
    assert datetime.fromisoformat(reloaded.last_login_at).tzinfo is not None
    assert reloaded.updated_at == admin.updated_at


def test_failed_logins_never_stamp_last_login(
    client: TestClient,
    runtime: AuthRuntime,
):
    admin, user = _accounts(runtime)

    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer", "password": "wrong-password"},
    )
    # 密碼對但沒有後台權限：403 也是登入失敗，不能算一次登入。
    portal_denied = client.post(
        "/api/v1/auth/admin-login",
        json={"username": "viewer", "password": _USER_PASSWORD},
    )
    runtime.users.set_disabled_guarded(
        actor_id=admin.id, user_id=user.id, disabled=True,
    )
    disabled = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer", "password": _USER_PASSWORD},
    )

    assert wrong_password.status_code == 401
    assert portal_denied.status_code == 403
    assert disabled.status_code == 401
    assert _last_login(runtime, user.id) is None


def test_temporary_login_stamps_the_same_users_column(
    client: TestClient,
    runtime: AuthRuntime,
):
    _accounts(runtime)
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
    created = client.post(
        "/api/v1/temporary-accounts/batches",
        headers=_admin_headers(client),
        json={
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
        },
    )
    assert created.status_code == 201
    credential = created.json()["credentials"][0]
    assert _last_login(runtime, credential["user_id"]) is None

    wrong = client.post(
        "/api/v1/auth/temporary-login", json={"password": "A" * 20},
    )
    assert wrong.status_code == 401
    assert _last_login(runtime, credential["user_id"]) is None

    response = client.post(
        "/api/v1/auth/temporary-login",
        json={"password": credential["password"]},
    )
    assert response.status_code == 200
    assert _last_login(runtime, credential["user_id"]) is not None


def test_account_list_reports_last_login_and_api_key_use(
    client: TestClient,
    runtime: AuthRuntime,
):
    admin, user = _accounts(runtime)
    headers = _admin_headers(client)

    before = {
        row["username"]: row
        for row in client.get("/api/v1/users", headers=headers).json()
    }
    assert before["viewer"]["last_login_at"] is None
    assert before["viewer"]["api_key_last_used_at"] is None
    assert before["admin"]["last_login_at"] is not None

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer", "password": _USER_PASSWORD},
    )
    assert login.status_code == 200
    _, secret = runtime.api_keys.create(
        actor_id=user.id, user_id=user.id, label="service",
    )
    _, used = runtime.api_keys.authenticate(secret)

    after = {
        row["username"]: row
        for row in client.get("/api/v1/users", headers=headers).json()
    }
    assert after["viewer"]["last_login_at"] == _last_login(runtime, user.id)
    assert after["viewer"]["api_key_last_used_at"] == used.last_used_at

    # 單筆操作回傳的列會直接替換前端列表，欄位不能在這裡變回空值。
    revoked = client.post(
        f"/api/v1/users/{user.id}/revoke",
        headers={**headers, "Origin": "http://testserver"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["last_login_at"] == after["viewer"]["last_login_at"]
    assert revoked.json()["api_key_last_used_at"] == used.last_used_at


def test_api_key_last_use_counts_revoked_keys(runtime: AuthRuntime):
    _, user = _accounts(runtime)
    record, secret = runtime.api_keys.create(
        actor_id=user.id, user_id=user.id, label="old",
    )
    _, used = runtime.api_keys.authenticate(secret)
    runtime.api_keys.revoke(actor_id=user.id, key_id=record.key_id)

    assert runtime.api_keys.last_used_at_for_user(user.id) == used.last_used_at

"""Kiosk (展示機台) account flag and the settings-unlock password check."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.attempt_limiter import FailedAttemptLimiter
from app.auth.database import AuthDatabase
from app.auth.models import AccountRole, ResourceType, ResourceVisibility
from app.auth.passwords import hash_password
from app.auth.repositories import UserRepository
from app.auth.routes import auth_router, temporary_accounts_router, users_router
from app.auth.runtime import AuthRuntime, build_auth_runtime, get_auth_runtime
from app.config import TTSRouterConfig

_ADMIN_PASSWORD = "admin-password"
_OTHER_ADMIN_PASSWORD = "other-admin-password"
_USER_PASSWORD = "user-password"
_ROOT_PASSWORD = "root-password"
_ORIGIN = {"Origin": "http://testserver"}


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


def _register_resources(runtime: AuthRuntime) -> None:
    for resource_type, resource_id in (
        (ResourceType.PROJECT, "kiosk-project"),
        (ResourceType.AVATAR_CHARACTER, "kiosk-character"),
        (ResourceType.CUSTOM_VOICE, "kiosk-voice"),
    ):
        runtime.resources.register(
            resource_type=resource_type,
            resource_id=resource_id,
            owner_user_id=None,
            visibility=ResourceVisibility.SYSTEM_PUBLIC,
        )


def _grants() -> dict[str, list[str]]:
    return {
        "projects": ["kiosk-project"],
        "avatar_characters": ["kiosk-character"],
        "custom_voices": ["kiosk-voice"],
        "avatar_mascots": [],
        "avatar_backgrounds": [],
        "asr_engines": [],
    }


def _defaults() -> dict[str, str]:
    return {
        "project_id": "kiosk-project",
        "character_id": "kiosk-character",
        "voice_provider": "indextts",
        "voice_id": "kiosk-voice",
        "mascot_id": "",
        "background_id": "",
    }


def _bearer(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _setup(runtime: AuthRuntime):
    _register_resources(runtime)
    admin = runtime.users.create(
        username="admin",
        password_hash=hash_password(_ADMIN_PASSWORD),
        role=AccountRole.ADMIN,
    )
    user = runtime.users.create(
        username="booth",
        password_hash=hash_password(_USER_PASSWORD),
        role=AccountRole.USER,
        created_by=admin.id,
    )
    return admin, user


def test_kiosk_column_defaults_off_and_migration_is_rerunnable(tmp_path: Path):
    database = AuthDatabase(tmp_path / "accounts.db")
    database.initialize()
    users = UserRepository(database)
    existing = users.create(
        username="legacy",
        password_hash="hash",
        role=AccountRole.USER,
    )

    # 模擬升級前的資料庫：欄位與遷移紀錄都還不存在。
    with database.transaction(write=True) as connection:
        connection.execute("ALTER TABLE users DROP COLUMN kiosk")
        connection.execute("DELETE FROM schema_migrations WHERE version = 16")
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
    assert columns["kiosk"]["notnull"] == 1
    assert columns["kiosk"]["dflt_value"] == "0"
    assert applied.count(16) == 1
    reloaded = users.get_by_id(existing.id)
    assert reloaded is not None and reloaded.kiosk is False
    assert users.create(
        username="fresh", password_hash="hash", role=AccountRole.USER,
    ).kiosk is False


def test_me_and_login_report_kiosk_and_admin_toggle_keeps_session(
    client: TestClient,
    runtime: AuthRuntime,
):
    admin, user = _setup(runtime)
    user_headers = _bearer(client, "booth", _USER_PASSWORD)
    assert client.get("/api/v1/auth/me", headers=user_headers).json()["kiosk"] is False

    admin_headers = _bearer(client, "admin", _ADMIN_PASSWORD)
    listed = client.get("/api/v1/users", headers=admin_headers).json()
    assert {item["username"]: item["kiosk"] for item in listed}["booth"] is False

    body = {"grants": _grants(), "defaults": _defaults(), "kiosk": True}
    updated = client.put(
        f"/api/v1/users/{user.id}/access", headers=admin_headers, json=body,
    )
    assert updated.status_code == 200
    assert updated.json()["kiosk"] is True

    # 切換展示機台不撤銷 session，現場機台不會被登出，下一次 /me 就看得到。
    me = client.get("/api/v1/auth/me", headers=user_headers)
    assert me.status_code == 200
    assert me.json()["kiosk"] is True
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "booth", "password": _USER_PASSWORD},
    )
    assert login.json()["account"]["kiosk"] is True
    listed = client.get("/api/v1/users", headers=admin_headers).json()
    assert {item["username"]: item["kiosk"] for item in listed}["booth"] is True

    # 舊版前端不送 kiosk：保持原值，不會被默默清掉。
    del body["kiosk"]
    unchanged = client.put(
        f"/api/v1/users/{user.id}/access", headers=admin_headers, json=body,
    )
    assert unchanged.json()["kiosk"] is True

    body["kiosk"] = False
    cleared = client.put(
        f"/api/v1/users/{user.id}/access", headers=admin_headers, json=body,
    )
    assert cleared.json()["kiosk"] is False
    assert client.get("/api/v1/auth/me", headers=user_headers).json()["kiosk"] is False


def test_kiosk_update_follows_account_management_policy(
    client: TestClient,
    runtime: AuthRuntime,
):
    admin, user = _setup(runtime)
    root = runtime.users.create_root(
        username="ai360",
        password_hash=hash_password(_ROOT_PASSWORD),
    )
    runtime.users.create(
        username="other-admin",
        password_hash=hash_password(_OTHER_ADMIN_PASSWORD),
        role=AccountRole.ADMIN,
    )
    body = {"grants": _grants(), "defaults": _defaults(), "kiosk": True}

    other_admin = _bearer(client, "other-admin", _OTHER_ADMIN_PASSWORD)
    foreign = client.put(
        f"/api/v1/users/{user.id}/access", headers=other_admin, json=body,
    )
    assert foreign.status_code == 403

    regular = _bearer(client, "booth", _USER_PASSWORD)
    assert client.put(
        f"/api/v1/users/{user.id}/access", headers=regular, json=body,
    ).status_code == 403

    admin_headers = _bearer(client, "admin", _ADMIN_PASSWORD)
    assert client.put(
        f"/api/v1/users/{root.id}/access", headers=admin_headers, json=body,
    ).status_code == 403
    assert client.put(
        f"/api/v1/users/{admin.id}/access", headers=admin_headers, json=body,
    ).status_code == 403

    stored = runtime.users.get_by_id(user.id)
    assert stored is not None and stored.kiosk is False

    root_headers = _bearer(client, "ai360", _ROOT_PASSWORD)
    assert client.put(
        f"/api/v1/users/{user.id}/access", headers=root_headers, json=body,
    ).json()["kiosk"] is True


def test_admin_can_create_a_kiosk_account(client: TestClient, runtime: AuthRuntime):
    _setup(runtime)
    admin_headers = _bearer(client, "admin", _ADMIN_PASSWORD)
    created = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": "lobby",
            "password": "lobby-password",
            "access": {
                "grants": _grants(),
                "defaults": _defaults(),
                "kiosk": True,
            },
        },
    )
    assert created.status_code == 201
    assert created.json()["kiosk"] is True
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "lobby", "password": "lobby-password"},
    )
    assert login.json()["account"]["kiosk"] is True


def test_verify_password_checks_current_account_without_touching_session(
    client: TestClient,
    runtime: AuthRuntime,
):
    _setup(runtime)
    headers = _bearer(client, "booth", _USER_PASSWORD)
    client.cookies.clear()

    ok = client.post(
        "/api/v1/auth/verify-password",
        headers=headers,
        json={"password": _USER_PASSWORD},
    )
    assert ok.status_code == 204
    assert ok.content == b""
    assert "set-cookie" not in ok.headers

    # 別的帳號的密碼不算數，打錯回 400（401 會被前台當成登出）。
    wrong = client.post(
        "/api/v1/auth/verify-password",
        headers=headers,
        json={"password": _ADMIN_PASSWORD},
    )
    assert wrong.status_code == 400
    assert wrong.json() == {"detail": "密碼不正確"}
    assert "set-cookie" not in wrong.headers
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    # Cookie 登入的前台同樣適用，回應不換發 cookie。
    client.post(
        "/api/v1/auth/login",
        json={"username": "booth", "password": _USER_PASSWORD},
    )
    session_cookie = client.cookies.get("openvman_session")
    assert session_cookie
    via_cookie = client.post(
        "/api/v1/auth/verify-password",
        headers=_ORIGIN,
        json={"password": _USER_PASSWORD},
    )
    assert via_cookie.status_code == 204
    assert "set-cookie" not in via_cookie.headers
    assert client.cookies.get("openvman_session") == session_cookie


def test_verify_password_requires_a_session(client: TestClient, runtime: AuthRuntime):
    _setup(runtime)
    response = client.post(
        "/api/v1/auth/verify-password",
        json={"password": _USER_PASSWORD},
    )
    assert response.status_code == 401


def test_verify_password_for_temporary_kiosk_batch(
    client: TestClient,
    runtime: AuthRuntime,
):
    _setup(runtime)
    admin_headers = _bearer(client, "admin", _ADMIN_PASSWORD)
    created = client.post(
        "/api/v1/temporary-accounts/batches",
        headers=admin_headers,
        json={"grants": _grants(), "defaults": _defaults(), "kiosk": True},
    )
    assert created.status_code == 201
    assert created.json()["kiosk"] is True
    first, second = (item["password"] for item in created.json()["credentials"][:2])

    batches = client.get(
        "/api/v1/temporary-accounts/batches", headers=admin_headers,
    ).json()
    assert batches[0]["kiosk"] is True
    assert all(account["kiosk"] is True for account in batches[0]["accounts"])

    login = client.post("/api/v1/auth/temporary-login", json={"password": first})
    assert login.status_code == 200
    assert login.json()["account"]["kiosk"] is True
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    client.cookies.clear()
    assert client.get("/api/v1/auth/me", headers=headers).json()["kiosk"] is True

    assert client.post(
        "/api/v1/auth/verify-password", headers=headers, json={"password": first},
    ).status_code == 204
    # 同一批的另一組臨時密碼不是這個帳號的。
    assert client.post(
        "/api/v1/auth/verify-password", headers=headers, json={"password": second},
    ).status_code == 400

    plain = client.post(
        "/api/v1/temporary-accounts/batches",
        headers=admin_headers,
        json={"grants": _grants(), "defaults": _defaults()},
    )
    assert plain.json()["kiosk"] is False


def test_verify_password_throttles_repeated_failures_per_account(
    client: TestClient,
    runtime: AuthRuntime,
):
    _setup(runtime)
    booth = _bearer(client, "booth", _USER_PASSWORD)
    admin = _bearer(client, "admin", _ADMIN_PASSWORD)
    client.cookies.clear()

    for _ in range(5):
        assert client.post(
            "/api/v1/auth/verify-password",
            headers=booth,
            json={"password": "wrong-password"},
        ).status_code == 400

    locked = client.post(
        "/api/v1/auth/verify-password",
        headers=booth,
        json={"password": _USER_PASSWORD},
    )
    assert locked.status_code == 429
    assert locked.json() == {"detail": "嘗試太多次，請稍後再試"}
    assert int(locked.headers["retry-after"]) > 0
    # 鎖住的是驗證密碼，不是 session。
    assert client.get("/api/v1/auth/me", headers=booth).status_code == 200

    # 計數是每個帳號各自算。
    assert client.post(
        "/api/v1/auth/verify-password",
        headers=admin,
        json={"password": _ADMIN_PASSWORD},
    ).status_code == 204


def test_attempt_limiter_window_and_reset():
    now = [1000.0]
    limiter = FailedAttemptLimiter(
        max_failures=3, window_seconds=60, clock=lambda: now[0],
    )
    for _ in range(2):
        limiter.record_failure("a")
    assert limiter.retry_after("a") is None
    limiter.reset("a")
    for _ in range(2):
        limiter.record_failure("a")
    now[0] += 30
    limiter.record_failure("a")
    assert limiter.retry_after("a") == 30
    assert limiter.retry_after("b") is None

    now[0] += 30
    # 最早那次失敗滑出視窗後就能再試。
    assert limiter.retry_after("a") is None
    # 剩下 t=1030 那次，再錯兩次又滿三次，要等它在 t=1090 滑出去。
    limiter.record_failure("a")
    assert limiter.retry_after("a") is None
    limiter.record_failure("a")
    assert limiter.retry_after("a") == 30

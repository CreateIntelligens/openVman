"""Authentication and account-administration API tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.middleware import FailClosedAuthMiddleware
from app.auth.models import ResourceType, ResourceVisibility
from app.auth.routes import auth_router, users_router
from app.auth.runtime import AuthRuntime, build_auth_runtime, get_auth_runtime
from app.config import TTSRouterConfig

_ADMIN_PASSWORD = "admin-password"
_USER_PASSWORD = "user-password"


@pytest.fixture()
def runtime(tmp_path: Path) -> AuthRuntime:
    config = TTSRouterConfig(
        _env_file=None,
        env="dev",
        session_jwt_secret="test-only-session-secret",
        auth_database_path=str(tmp_path / "accounts.db"),
    )
    return build_auth_runtime(config)


@pytest.fixture()
def client(runtime: AuthRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(users_router)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    return TestClient(app)


def _bootstrap_admin(runtime: AuthRuntime):
    from app.auth.models import AccountRole
    from app.auth.passwords import hash_password

    return runtime.users.create(
        username="admin",
        password_hash=hash_password(_ADMIN_PASSWORD),
        role=AccountRole.ADMIN,
    )


def _login(client: TestClient, username: str, password: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()


def _origin_headers() -> dict[str, str]:
    return {"Origin": "http://testserver"}


def test_login_me_bearer_cookie_logout_and_generic_failures(client, runtime):
    admin = _bootstrap_admin(runtime)

    wrong_password = client.post(
        "/api/auth/login",
        json={"username": admin.username, "password": "wrong-password"},
    )
    unknown_account = client.post(
        "/api/auth/login",
        json={"username": "missing", "password": "wrong-password"},
    )
    assert wrong_password.status_code == unknown_account.status_code == 401
    assert (
        wrong_password.json()
        == unknown_account.json()
        == {"detail": "Invalid credentials"}
    )

    login = _login(client, " ADMIN ", _ADMIN_PASSWORD)
    assert login["account"] == {
        "id": admin.id,
        "username": "admin",
        "role": "admin",
        "kind": "formal",
        "disabled": False,
        "created_at": admin.created_at,
        "created_by": None,
        "expires_at": None,
        "remaining_seconds": None,
        "defaults": None,
    }
    assert login["token"]

    cookie_me = client.get("/api/auth/me")
    bearer_me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {login['token']}"},
    )
    assert cookie_me.status_code == bearer_me.status_code == 200
    assert cookie_me.json() == bearer_me.json() == login["account"]

    missing_origin = client.post("/api/auth/logout")
    assert missing_origin.status_code == 403
    logout = client.post("/api/auth/logout", headers=_origin_headers())
    assert logout.status_code == 200
    assert logout.json() == {"ok": True}
    assert client.get("/api/auth/me").status_code == 401


def test_production_login_cookie_has_required_flags(tmp_path: Path):
    config = TTSRouterConfig(
        _env_file=None,
        env="prod",
        session_jwt_secret="test-only-session-secret",
        auth_database_path=str(tmp_path / "accounts.db"),
    )
    runtime = build_auth_runtime(config)
    _bootstrap_admin(runtime)
    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime

    with TestClient(app, base_url="https://testserver") as secure_client:
        response = secure_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": _ADMIN_PASSWORD},
        )

    cookie = response.headers["set-cookie"]
    assert "openvman_session=" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie


def test_admin_lifecycle_creator_revocation_and_immediate_disable(client, runtime):
    admin = _bootstrap_admin(runtime)
    admin_login = _login(client, admin.username, _ADMIN_PASSWORD)
    admin_headers = {
        "Authorization": f"Bearer {admin_login['token']}",
    }

    created = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "Alice",
            "password": _USER_PASSWORD,
            "role": "user",
        },
    )
    assert created.status_code == 201
    user = created.json()
    assert user["created_by"] == admin.id
    assert user["resource_counts"] == {}

    duplicate = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": " alice ",
            "password": _USER_PASSWORD,
            "role": "user",
        },
    )
    assert duplicate.status_code == 409

    user_login = _login(client, "alice", _USER_PASSWORD)
    user_headers = {"Authorization": f"Bearer {user_login['token']}"}
    denied = client.get("/api/users", headers=user_headers)
    assert denied.status_code == 403

    revoked = client.post(f"/api/users/{user['id']}/revoke", headers=admin_headers)
    assert revoked.status_code == 200
    assert client.get("/api/auth/me", headers=user_headers).status_code == 401

    user_login = _login(client, "alice", _USER_PASSWORD)
    user_headers = {"Authorization": f"Bearer {user_login['token']}"}
    disabled = client.patch(
        f"/api/users/{user['id']}/disabled",
        headers=admin_headers,
        json={"disabled": True},
    )
    assert disabled.status_code == 200
    assert disabled.json()["disabled"] is True
    assert client.get("/api/auth/me", headers=user_headers).status_code == 401

    enabled = client.patch(
        f"/api/users/{user['id']}/disabled",
        headers=admin_headers,
        json={"disabled": False},
    )
    assert enabled.status_code == 200
    assert enabled.json()["disabled"] is False


def test_account_deletion_resource_counts_and_admin_self_protection(client, runtime):
    admin = _bootstrap_admin(runtime)
    admin_login = _login(client, admin.username, _ADMIN_PASSWORD)
    headers = {"Authorization": f"Bearer {admin_login['token']}"}
    self_disable = client.patch(
        f"/api/users/{admin.id}/disabled",
        headers=headers,
        json={"disabled": True},
    )
    self_delete = client.delete(f"/api/users/{admin.id}", headers=headers)
    assert self_disable.status_code == self_delete.status_code == 409

    created = client.post(
        "/api/users",
        headers=headers,
        json={
            "username": "resource-owner",
            "password": _USER_PASSWORD,
            "role": "user",
        },
    ).json()
    runtime.resources.register(
        resource_type=ResourceType.PROJECT,
        resource_id="project-owned",
        owner_user_id=created["id"],
        visibility=ResourceVisibility.PRIVATE,
    )
    account_list = client.get("/api/users", headers=headers)
    listed_owner = next(
        account for account in account_list.json() if account["id"] == created["id"]
    )
    assert listed_owner["resource_counts"] == {"project": 1}
    client.patch(
        f"/api/users/{created['id']}/disabled",
        headers=headers,
        json={"disabled": True},
    )

    blocked = client.delete(f"/api/users/{created['id']}", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["resource_counts"] == {"project": 1}
    assert runtime.users.get_by_id(created["id"]) is not None

    runtime.resources.unregister(ResourceType.PROJECT, "project-owned")
    deleted = client.delete(f"/api/users/{created['id']}", headers=headers)
    assert deleted.status_code == 204
    assert runtime.users.get_by_id(created["id"]) is None


def test_fail_closed_middleware_ignores_query_tokens_and_enforces_csrf(runtime):
    admin = _bootstrap_admin(runtime)
    token = runtime.tokens.issue(admin)
    app = FastAPI()

    @app.get("/healthz")
    def public_health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/private")
    def private_get() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/private")
    def private_post() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(FailClosedAuthMiddleware, runtime=runtime)
    isolated_client = TestClient(app)

    assert isolated_client.get("/healthz").status_code == 200
    assert isolated_client.get("/private").status_code == 401
    assert isolated_client.get(f"/private?token={token}").status_code == 401

    isolated_client.cookies.set("openvman_session", token)
    assert (
        isolated_client.post(
            "/private",
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    bearer = isolated_client.post(
        "/private",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert bearer.status_code == 200

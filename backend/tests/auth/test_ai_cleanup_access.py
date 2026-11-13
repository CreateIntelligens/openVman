"""「AI 整理排版」 per-account permission: storage, account API and the Brain proxy guard."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app import brain_proxy
from app.ai_cleanup_guard import REFUSAL, AiCleanupRefused, guard_ai_cleanup
from app.auth.database import AuthDatabase
from app.auth.dependencies import AuthTransport, CurrentAccount, get_current_account
from app.auth.models import AccountRole, AccountType, UserRecord, has_ai_cleanup_access
from app.auth.passwords import hash_password
from app.auth.routes import auth_router, temporary_accounts_router, users_router
from app.auth.runtime import AuthRuntime, build_auth_runtime, get_auth_runtime
from app.auth.user_repository import UserRepository
from app.config import TTSRouterConfig

_ADMIN_PASSWORD = "admin-password"
_USER_PASSWORD = "user-password"


def _user(role: AccountRole = AccountRole.USER, *, ai: bool = False) -> UserRecord:
    return UserRecord(
        id=f"{role.value}-{int(ai)}", username="u", username_normalized="u", password_hash="x",
        role=role, account_type=AccountType.FORMAL, disabled=False, token_version=0,
        created_at="t", updated_at="t", created_by=None, ai_cleanup_access=ai,
    )


def _current(user: UserRecord, **extra) -> CurrentAccount:
    return CurrentAccount(user=user, transport=next(iter(AuthTransport)), **extra)


# --- storage --------------------------------------------------------------------


def test_existing_accounts_start_without_the_permission_and_the_migration_reruns(tmp_path: Path):
    database = AuthDatabase(tmp_path / "accounts.db")
    database.initialize()
    users = UserRepository(database)
    legacy = users.create(username="legacy", password_hash="hash", role=AccountRole.USER)
    with database.transaction(write=True) as connection:
        connection.execute("ALTER TABLE users DROP COLUMN ai_cleanup_access")
        connection.execute("DELETE FROM schema_migrations WHERE version = 27")
    database.initialize()
    database.initialize()

    with database.transaction() as connection:
        column = {row["name"]: row for row in connection.execute("PRAGMA table_info(users)")}["ai_cleanup_access"]
        applied = [row["version"] for row in connection.execute("SELECT version FROM schema_migrations")]
    assert column["notnull"] == 1 and column["dflt_value"] == "0"
    assert applied.count(27) == 1
    reloaded = users.get_by_id(legacy.id)
    assert reloaded is not None and reloaded.ai_cleanup_access is False


def test_administrators_always_have_it_and_users_only_when_granted():
    assert has_ai_cleanup_access(_user(AccountRole.ROOT))
    assert has_ai_cleanup_access(_user(AccountRole.ADMIN))
    assert not has_ai_cleanup_access(_user())
    assert has_ai_cleanup_access(_user(ai=True))


# --- account API ----------------------------------------------------------------


@pytest.fixture()
def runtime(tmp_path: Path) -> AuthRuntime:
    return build_auth_runtime(TTSRouterConfig(
        _env_file=None, env="dev", session_jwt_secret="test-only-session-secret-for-tests-32",
        auth_database_path=str(tmp_path / "accounts.db"),
    ))


@pytest.fixture()
def client(runtime: AuthRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(temporary_accounts_router)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    return TestClient(app)


def _bearer(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_the_account_api_reports_and_changes_the_permission(client: TestClient, runtime: AuthRuntime):
    from tests.auth.test_kiosk import _defaults, _grants, _register_resources

    _register_resources(runtime)
    admin = runtime.users.create(username="admin", password_hash=hash_password(_ADMIN_PASSWORD), role=AccountRole.ADMIN)
    user = runtime.users.create(username="clerk", password_hash=hash_password(_USER_PASSWORD), role=AccountRole.USER,
                                created_by=admin.id)
    admin_headers = _bearer(client, "admin", _ADMIN_PASSWORD)
    user_headers = _bearer(client, "clerk", _USER_PASSWORD)

    assert client.get("/api/v1/auth/me", headers=admin_headers).json()["ai_cleanup_access"] is True
    assert client.get("/api/v1/auth/me", headers=user_headers).json()["ai_cleanup_access"] is False

    body = {"grants": _grants(), "defaults": _defaults(), "ai_cleanup_access": True}
    updated = client.put(f"/api/v1/users/{user.id}/access", headers=admin_headers, json=body)
    assert updated.status_code == 200 and updated.json()["ai_cleanup_access"] is True
    # 不撤銷 session：下一個請求就看得到。
    assert client.get("/api/v1/auth/me", headers=user_headers).json()["ai_cleanup_access"] is True

    del body["ai_cleanup_access"]
    kept = client.put(f"/api/v1/users/{user.id}/access", headers=admin_headers, json=body)
    assert kept.json()["ai_cleanup_access"] is True
    # 一般帳號不能自己開。
    assert client.put(f"/api/v1/users/{user.id}/access", headers=user_headers,
                      json={**body, "ai_cleanup_access": False}).status_code == 403


def test_a_new_account_can_be_created_with_the_permission(client: TestClient, runtime: AuthRuntime):
    from tests.auth.test_kiosk import _defaults, _grants, _register_resources

    _register_resources(runtime)
    runtime.users.create(username="admin", password_hash=hash_password(_ADMIN_PASSWORD), role=AccountRole.ADMIN)
    admin_headers = _bearer(client, "admin", _ADMIN_PASSWORD)
    created = client.post("/api/v1/users", headers=admin_headers, json={
        "username": "writer", "password": "writer-password-1",
        "access": {"grants": _grants(), "defaults": _defaults(), "ai_cleanup_access": True},
    })
    assert created.status_code in (200, 201), created.text
    assert created.json()["ai_cleanup_access"] is True


def test_temporary_accounts_default_off_and_can_be_created_with_it(client: TestClient, runtime: AuthRuntime):
    from tests.auth.test_kiosk import _defaults, _grants, _register_resources

    _register_resources(runtime)
    runtime.users.create(username="admin", password_hash=hash_password(_ADMIN_PASSWORD), role=AccountRole.ADMIN)
    admin_headers = _bearer(client, "admin", _ADMIN_PASSWORD)
    for enabled in (False, True):
        payload = {"grants": _grants(), "defaults": _defaults(), **({"ai_cleanup_access": True} if enabled else {})}
        batch = client.post("/api/v1/temporary-accounts/batches", headers=admin_headers, json=payload)
        assert batch.status_code in (200, 201), batch.text
        assert batch.json()["ai_cleanup_access"] is enabled
        for credential in batch.json()["credentials"]:
            stored = runtime.users.get_by_id(credential["user_id"])
            assert stored is not None and stored.ai_cleanup_access is enabled


# --- the guard ------------------------------------------------------------------


def _commit(**payload) -> bytes:
    return json.dumps({"project_id": "p", **payload}).encode()


@pytest.mark.parametrize("current", [None, _current(_user())])
def test_without_the_permission_cleanup_requests_are_refused(current):
    for path in ("knowledge/renormalize", "knowledge/renormalize/preview"):
        with pytest.raises(AiCleanupRefused, match="AI 整理排版"):
            guard_ai_cleanup(path, "POST", b'{"path": "knowledge/a.md"}', current)
    with pytest.raises(AiCleanupRefused):
        guard_ai_cleanup("knowledge/raw/commit", "POST", _commit(normalize=True), current)


def test_without_the_permission_an_import_without_normalize_skips_the_ai():
    forwarded = guard_ai_cleanup("knowledge/raw/commit", "POST", _commit(paths=["a.pdf"]), _current(_user()))
    assert json.loads(forwarded) == {"project_id": "p", "paths": ["a.pdf"], "normalize": False}
    explicit = _commit(normalize=False)
    assert guard_ai_cleanup("knowledge/raw/commit", "POST", explicit, _current(_user())) == explicit


def test_the_permission_lets_every_cleanup_through_unchanged():
    for current in (_current(_user(ai=True)), _current(_user(AccountRole.ADMIN))):
        body = _commit()
        assert guard_ai_cleanup("knowledge/raw/commit", "POST", body, current) == body
        assert guard_ai_cleanup("knowledge/renormalize", "POST", b"{}", current) == b"{}"


def test_api_keys_follow_their_owner_and_embed_keys_never_clean_up():
    owner_allowed = _current(_user(ai=True), api_key=MagicMock())
    assert guard_ai_cleanup("knowledge/renormalize", "POST", b"{}", owner_allowed) == b"{}"
    owner_denied = _current(_user(), api_key=MagicMock())
    with pytest.raises(AiCleanupRefused):
        guard_ai_cleanup("knowledge/renormalize", "POST", b"{}", owner_denied)
    with pytest.raises(AiCleanupRefused):
        guard_ai_cleanup("knowledge/renormalize", "POST", b"{}", _current(_user(AccountRole.ADMIN), embed_key=MagicMock()))


def test_applying_a_preview_and_other_routes_are_not_touched():
    body = b'{"path": "knowledge/a.md", "content": "x"}'
    assert guard_ai_cleanup("knowledge/renormalize/apply", "POST", body, None) == body
    assert guard_ai_cleanup("knowledge/document", "PUT", body, None) == body


# --- through the proxy ----------------------------------------------------------


def _proxy_app(current: CurrentAccount | None) -> FastAPI:
    app = FastAPI()
    app.include_router(brain_proxy.router)
    app.dependency_overrides[get_current_account] = lambda: current

    @app.middleware("http")
    async def _account(request: Request, call_next):
        request.state.current_account = current
        return await call_next(request)

    return app


def _upstream() -> MagicMock:
    upstream = MagicMock(status_code=202, headers={"content-type": "application/json"})
    upstream.aread = AsyncMock(return_value=b'{"status": "started"}')
    upstream.aclose = AsyncMock(return_value=None)
    client = MagicMock()
    client.build_request = MagicMock(side_effect=lambda **kwargs: kwargs)
    client.send = AsyncMock(return_value=upstream)
    return client


@pytest.mark.parametrize(
    "current, payload, expected",
    [
        (_current(_user()), {"project_id": "p", "normalize": True}, 403),
        (_current(_user()), {"project_id": "p"}, False),
        (_current(_user(ai=True)), {"project_id": "p", "normalize": True}, True),
    ],
)
def test_the_proxy_applies_the_guard(current, payload, expected):
    client = _upstream()
    cfg = MagicMock(brain_url="http://brain:8100", resolved_brain_chat_url="http://brain:8100",
                    gateway_internal_token="t", brain_proxy_max_body_bytes=1024 * 1024)
    with (
        patch("app.brain_proxy.get_tts_config", return_value=cfg),
        patch("app.brain_proxy._http.get", return_value=client),
        patch("app.brain_proxy._authorize_project_context", AsyncMock(return_value="p")),
    ):
        response = TestClient(_proxy_app(current)).post("/api/v1/knowledge/raw/commit", json=payload)
    if expected == 403:
        assert response.status_code == 403
        assert response.json()["detail"] == REFUSAL
        client.send.assert_not_called()
        return
    sent = client.build_request.call_args.kwargs["content"]
    assert json.loads(sent).get("normalize") is expected

"""Credential secrecy, live authorization, and HTTP/WebSocket integration."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated

import pytest
from app.auth.api_key_routes import router
from app.auth.dependencies import (
    AuthTransport,
    CurrentAccount,
    authenticate_websocket,
    get_current_account,
    require_root,
)
from app.auth.middleware import FailClosedAuthMiddleware
from app.auth.models import AccountRole, AccountType, ResourceType
from app.auth.policy import AccountPolicyError
from app.auth.resources import ResourceNotFoundError, resolve_resource
from app.auth.runtime import build_auth_runtime, get_auth_runtime
from app.config import TTSRouterConfig
from fastapi import Depends, FastAPI, HTTPException, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture
def setup(tmp_path):
    runtime = build_auth_runtime(
        TTSRouterConfig(
            _env_file=None,
            env="dev",
            session_jwt_secret="test-only-api-key-session-secret-32",
            auth_database_path=str(tmp_path / "auth.db"),
        )
    )
    root = runtime.users.create_root(username="ai360", password_hash="unused")
    owner = runtime.users.create(
        username="owner", password_hash="unused", role=AccountRole.USER
    )
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(FailClosedAuthMiddleware, runtime=runtime)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime

    @app.get("/probe")
    def probe(
        current: Annotated[CurrentAccount, Depends(get_current_account)],
    ):
        return {
            "user_id": current.user.id,
            "role": current.user.role.value,
            "transport": current.transport.value,
            "key_id": current.api_key.key_id if current.api_key else None,
        }

    @app.get("/root-probe")
    def root_probe(current: Annotated[CurrentAccount, Depends(require_root)]):
        return {"user_id": current.user.id}

    @app.get("/project/{project_id}")
    def project_probe(
        project_id: str,
        current: Annotated[CurrentAccount, Depends(get_current_account)],
    ):
        try:
            resource = resolve_resource(
                runtime.resources,
                current.user,
                ResourceType.PROJECT,
                project_id,
                admin_scopes=runtime.admin_scopes,
            )
        except ResourceNotFoundError as exc:
            raise HTTPException(status_code=404) from exc
        return {"project_id": resource.resource_id}

    @app.websocket("/socket")
    async def socket(websocket: WebSocket):
        try:
            current = authenticate_websocket(websocket, runtime)
        except HTTPException:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        await websocket.send_json({"user_id": current.user.id})
        await websocket.close()

    return runtime, root, owner, TestClient(app)


def _headers(runtime, user):
    return {"Authorization": f"Bearer {runtime.tokens.issue(user)}"}


def _issue(runtime, user, **overrides):
    return runtime.api_keys.create(
        actor_id=user.id, user_id=user.id, label="service", **overrides
    )


def test_secret_once_only_digest_persisted_and_safe_audit(setup):
    runtime, _, owner, client = setup
    response = client.post(
        "/api/v1/api-keys",
        headers=_headers(runtime, owner),
        json={"label": "service"},
    )
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    issued = response.json()
    secret = issued.pop("key")
    assert secret.startswith(f"ovk_{issued['key_id']}.")
    assert issued["expires_at"] is None
    assert issued["request_count"] == 0
    listing = client.get("/api/v1/api-keys", headers=_headers(runtime, owner))
    assert listing.json() == {"keys": [issued]}
    assert listing.headers["cache-control"] == "no-store"
    with runtime.database.transaction() as connection:
        row = dict(
            connection.execute("SELECT * FROM account_api_keys").fetchone()
        )
    digest = hashlib.sha256(secret.encode()).hexdigest()
    assert row.pop("credential_digest") == digest
    assert secret not in json.dumps(row)
    audit = runtime.auth_audit.list()[-1]
    assert audit.action == "api_key.created"
    assert json.loads(audit.metadata_json) == {"key_id": issued["key_id"]}
    assert secret not in repr(audit)
    assert digest not in repr(audit)


def test_key_bearer_preserves_identity_and_counts_http_and_ws_once(setup):
    runtime, _, owner, client = setup
    record, secret = _issue(runtime, owner)
    headers = {"Authorization": f"Bearer {secret}"}
    assert client.get("/probe", headers=headers).json() == {
        "user_id": owner.id,
        "role": "user",
        "transport": "api_key",
        "key_id": record.key_id,
    }
    with client.websocket_connect("/socket", headers=headers) as websocket:
        assert websocket.receive_json() == {"user_id": owner.id}
    metadata = runtime.api_keys.list_for_user(
        actor_id=owner.id, user_id=owner.id
    )[0]
    assert metadata.request_count == 2
    assert metadata.last_used_at is not None
    assert (
        client.get("/probe", headers=_headers(runtime, owner)).json()[
            "transport"
        ]
        == AuthTransport.BEARER.value
    )
    assert client.get("/probe", params={"key": secret}).status_code == 401
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"/socket?token={secret}"),
    ):
        pass


@pytest.mark.parametrize(
    "failure",
    [
        "malformed",
        "wrong",
        "unknown",
        "expired",
        "revoked",
        "disabled",
        "role",
        "version",
        "temporary",
        "invalid_expiry",
    ],
)
def test_invalid_credentials_fail_closed_without_counting(setup, failure):
    runtime, _, owner, client = setup
    record, secret = _issue(runtime, owner)
    with runtime.database.transaction(write=True) as connection:
        if failure == "malformed":
            secret = "ovk_bad"
        elif failure == "wrong":
            secret = secret[:-1] + ("A" if secret[-1] != "A" else "B")
        elif failure == "unknown":
            secret = "ovk_" + "0" * 32 + "." + "A" * 43
        elif failure in {"expired", "invalid_expiry", "revoked"}:
            column = "revoked_at" if failure == "revoked" else "expires_at"
            value = (
                "invalid"
                if failure == "invalid_expiry"
                else (
                    datetime.now(timezone.utc) - timedelta(days=1)
                ).isoformat()
            )
            connection.execute(
                f"UPDATE account_api_keys SET {column} = ? WHERE key_id = ?",
                (value, record.key_id),
            )
        else:
            updates = {
                "disabled": "disabled = 1",
                "role": "role = 'admin'",
                "version": "token_version = token_version + 1",
                "temporary": "account_type = 'temporary'",
            }
            connection.execute(
                f"UPDATE users SET {updates[failure]} WHERE id = ?",
                (owner.id,),
            )
    headers = {"Authorization": f"Bearer {secret}"}
    assert client.get("/probe", headers=headers).status_code == 401
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/socket", headers=headers),
    ):
        pass
    with runtime.database.transaction() as connection:
        assert connection.execute(
            "SELECT request_count, last_used_at FROM account_api_keys"
        ).fetchone()[:] == (0, None)


def test_revoke_is_retained_idempotent_and_invalidates_immediately(setup):
    runtime, _, owner, client = setup
    record, secret = _issue(runtime, owner)
    for _ in range(2):
        response = client.delete(
            f"/api/v1/api-keys/{record.key_id}",
            headers=_headers(runtime, owner),
        )
        assert response.json() == {"ok": True}
        assert response.headers["cache-control"] == "no-store"
    assert (
        client.get(
            "/probe", headers={"Authorization": f"Bearer {secret}"}
        ).status_code
        == 401
    )
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            "/socket", headers={"Authorization": f"Bearer {secret}"}
        ),
    ):
        pass
    assert (
        runtime.api_keys.list_for_user(actor_id=owner.id, user_id=owner.id)[
            0
        ].revoked_at
        is not None
    )
    assert [event.action for event in runtime.auth_audit.list()].count(
        "api_key.revoked"
    ) == 1


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("GET", "/api/v1/api-keys", None),
        ("POST", "/api/v1/api-keys", {"label": "delegated"}),
        ("DELETE", "/api/v1/api-keys/{key_id}", None),
    ],
)
def test_root_key_cannot_delegate_or_manage_credentials(
    setup, method, path, payload
):
    runtime, root, _, client = setup
    record, secret = _issue(runtime, root)
    assert (
        client.get(
            "/root-probe", headers={"Authorization": f"Bearer {secret}"}
        ).status_code
        == 200
    )
    response = client.request(
        method,
        path.format(key_id=record.key_id),
        json=payload,
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


def test_account_management_hierarchy_and_formal_requirement(setup):
    runtime, root, owner, client = setup
    admin = runtime.users.create(
        username="admin",
        password_hash="unused",
        role=AccountRole.ADMIN,
        created_by=root.id,
    )
    child = runtime.users.create(
        username="child",
        password_hash="unused",
        role=AccountRole.USER,
        created_by=admin.id,
    )
    for actor, target, expected in [
        (owner, admin, 403),
        (admin, root, 403),
        (admin, owner, 403),
        (admin, child, 201),
        (admin, admin, 201),
        (root, owner, 201),
    ]:
        response = client.post(
            "/api/v1/api-keys",
            headers=_headers(runtime, actor),
            json={"label": "test", "user_id": target.id},
        )
        assert response.status_code == expected
    assert (
        client.get(
            "/api/v1/api-keys",
            params={"user_id": owner.id},
            headers=_headers(runtime, admin),
        ).status_code
        == 403
    )
    record = runtime.api_keys.list_for_user(
        actor_id=root.id, user_id=owner.id
    )[0]
    assert (
        client.delete(
            f"/api/v1/api-keys/{record.key_id}",
            headers=_headers(runtime, admin),
        ).status_code
        == 403
    )
    temporary = runtime.users.create(
        username="temporary",
        password_hash="unused",
        role=AccountRole.USER,
        account_type=AccountType.TEMPORARY,
    )
    with pytest.raises(AccountPolicyError):
        _issue(runtime, temporary)
    assert (
        client.post(
            "/api/v1/api-keys",
            headers=_headers(runtime, root),
            json={"label": "test", "user_id": temporary.id},
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"label": " "}, 422),
        ({"label": "a" * 121}, 422),
        ({"label": "valid", "scopes": ["root"]}, 422),
        ({"label": "valid", "expires_at": "2030-01-01T00:00:00"}, 422),
        ({"label": "valid", "expires_at": "2000-01-01T00:00:00Z"}, 400),
        ({"label": "valid", "expires_at": 1893456000}, 422),
    ],
)
def test_strict_creation_validation_and_noncacheable_errors(
    setup, payload, expected
):
    runtime, _, owner, client = setup
    response = client.post(
        "/api/v1/api-keys", headers=_headers(runtime, owner), json=payload
    )
    assert response.status_code == expected
    assert response.headers["cache-control"] == "no-store"
    assert (
        runtime.api_keys.list_for_user(actor_id=owner.id, user_id=owner.id)
        == ()
    )


def test_live_resource_grants_apply_without_reissuing_key(setup):
    runtime, root, owner, client = setup
    runtime.resources.upsert_system_resource(
        resource_type=ResourceType.PROJECT, resource_id="partner"
    )
    _, secret = _issue(runtime, owner)
    headers = {"Authorization": f"Bearer {secret}"}
    assert client.get("/project/partner", headers=headers).status_code == 404
    with runtime.database.transaction(write=True) as connection:
        connection.execute(
            """
            INSERT INTO resource_grants (
                grantee_user_id, resource_type, resource_id, granted_by,
                created_at
            ) VALUES (?, 'project', 'partner', ?, ?)
            """,
            (owner.id, root.id, datetime.now(timezone.utc).isoformat()),
        )
    assert client.get("/project/partner", headers=headers).status_code == 200
    with runtime.database.transaction(write=True) as connection:
        connection.execute(
            "DELETE FROM resource_grants WHERE grantee_user_id = ?",
            (owner.id,),
        )
    assert client.get("/project/partner", headers=headers).status_code == 404


def test_migration_idempotence_preserves_issued_credentials(setup):
    runtime, _, owner, _ = setup
    record, secret = _issue(runtime, owner)
    runtime.database.initialize()
    runtime.database.initialize()
    authenticated, metadata = runtime.api_keys.authenticate(secret)
    assert authenticated.id == owner.id
    assert metadata.key_id == record.key_id
    assert metadata.request_count == 1


def test_scoped_admin_cannot_impersonate_account_with_more_resources(setup):
    runtime, root, _, client = setup
    admin = runtime.users.create(
        username="scoped",
        password_hash="unused",
        role=AccountRole.ADMIN,
        created_by=root.id,
    )
    child = runtime.users.create(
        username="child",
        password_hash="unused",
        role=AccountRole.USER,
        created_by=admin.id,
    )
    child_admin = runtime.users.create(
        username="child-admin",
        password_hash="unused",
        role=AccountRole.ADMIN,
        created_by=admin.id,
    )
    for project_id in ("allowed", "outside"):
        runtime.resources.upsert_system_resource(
            resource_type=ResourceType.PROJECT, resource_id=project_id
        )
    runtime.admin_scopes.replace(
        admin_user_id=admin.id,
        updated_by=root.id,
        scoped=True,
        resources=[(ResourceType.PROJECT, "allowed")],
    )
    with runtime.database.transaction(write=True) as connection:
        connection.execute(
            """
            INSERT INTO resource_grants (
                grantee_user_id, resource_type, resource_id, granted_by,
                created_at
            ) VALUES (?, 'project', 'allowed', ?, ?)
            """,
            (child.id, root.id, datetime.now(timezone.utc).isoformat()),
        )
    headers = _headers(runtime, admin)
    assert (
        client.post(
            "/api/v1/api-keys",
            headers=headers,
            json={"label": "child", "user_id": child.id},
        ).status_code
        == 201
    )
    # ROOT 可獨立擴大目標帳號權限；原管理者不得藉代發 key 取得新增資源。
    with runtime.database.transaction(write=True) as connection:
        connection.execute(
            """
            INSERT INTO resource_grants (
                grantee_user_id, resource_type, resource_id, granted_by,
                created_at
            ) VALUES (?, 'project', 'outside', ?, ?)
            """,
            (child.id, root.id, datetime.now(timezone.utc).isoformat()),
        )
    assert (
        client.post(
            "/api/v1/api-keys",
            headers=headers,
            json={"label": "outside", "user_id": child.id},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/api-keys",
            headers=headers,
            json={"label": "child-admin", "user_id": child_admin.id},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/api-keys",
            headers=_headers(runtime, root),
            json={"label": "root-issued", "user_id": child.id},
        ).status_code
        == 201
    )
    root_issued_admin_key = client.post(
        "/api/v1/api-keys",
        headers=_headers(runtime, root),
        json={"label": "admin-issued-by-root", "user_id": child_admin.id},
    ).json()
    assert (
        client.get(
            "/api/v1/api-keys",
            headers=headers,
            params={"user_id": child_admin.id},
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"/api/v1/api-keys/{root_issued_admin_key['key_id']}",
            headers=headers,
        ).status_code
        == 200
    )


def test_cookie_management_requires_same_origin_and_no_url_credentials(setup):
    runtime, _, owner, client = setup
    client.cookies.set("openvman_session", runtime.tokens.issue(owner))
    assert (
        client.post("/api/v1/api-keys", json={"label": "cookie"}).status_code
        == 403
    )
    response = client.post(
        "/api/v1/api-keys",
        json={"label": "cookie"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"


def test_multiple_keys_expiry_and_revocation_are_independent(setup):
    runtime, _, owner, _ = setup
    first, first_secret = _issue(
        runtime,
        owner,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    second, second_secret = _issue(runtime, owner)
    assert first.key_id != second.key_id
    assert first.expires_at is not None
    assert second.expires_at is None
    runtime.api_keys.revoke(actor_id=owner.id, key_id=first.key_id)
    with pytest.raises(ValueError):
        runtime.api_keys.authenticate(first_secret)
    assert runtime.api_keys.authenticate(second_secret)[0].id == owner.id

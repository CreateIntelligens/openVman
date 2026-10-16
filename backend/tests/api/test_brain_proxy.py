"""Tests for backend brain proxy facade routes."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.auth.dependencies import AuthTransport, CurrentAccount, get_current_account
from app.auth.models import (
    AccountRole,
    AccountType,
    ResourceType,
    UserRecord,
)
from app.auth.resources import ResourceAccess


def _mock_cfg():
    return MagicMock(
        brain_url="http://brain:8100",
        gateway_internal_token="internal-secret",
    )


def _request_with_headers(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/search",
            "raw_path": b"/api/v1/search",
            "query_string": b"",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
    )


def _make_response(
    *,
    status_code: int = 200,
    body: bytes = b'{"status":"ok"}',
    content_type: str = "application/json",
):
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"content-type": content_type}
    response.aread = AsyncMock(return_value=body)
    response.aclose = AsyncMock(return_value=None)
    response.aiter_bytes = MagicMock()
    return response


def _portal_current() -> CurrentAccount:
    return CurrentAccount(
        user=UserRecord(
            id="portal-user",
            username="portal-user",
            username_normalized="portal-user",
            password_hash="hash",
            role=AccountRole.USER,
            account_type=AccountType.FORMAL,
            disabled=False,
            token_version=0,
            created_at="2026-09-01T00:00:00+00:00",
            updated_at="2026-09-01T00:00:00+00:00",
            created_by=None,
            admin_portal_access=True,
        ),
        transport=AuthTransport.BEARER,
    )


@pytest.fixture()
def client():
    env = {"BRAIN_URL": "http://brain:8100"}
    with patch.dict(os.environ, env, clear=False):
        from app.config import get_tts_config

        get_tts_config.cache_clear()
        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def test_gateway_brain_proxy_forwards_to_brain_api(client: TestClient):
    upstream = _make_response()
    mock_client = MagicMock()
    mock_client.build_request = MagicMock(return_value="request")
    mock_client.send = AsyncMock(return_value=upstream)

    with (
        patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
        patch("app.brain_proxy._http.get", return_value=mock_client),
    ):
        response = client.get("/api/v1/health?project_id=default")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_client.build_request.assert_called_once()
    build_kwargs = mock_client.build_request.call_args.kwargs
    assert build_kwargs["url"] == "http://brain:8100/brain/health?project_id=default"
    assert build_kwargs["headers"]["X-Internal-Token"] == "internal-secret"


def test_trusted_headers_replace_forged_external_identity() -> None:
    from app.brain_proxy import _trusted_upstream_headers

    request = _request_with_headers(
        [
            (b"x-openvman-user-id", b"forged-user"),
            (b"x-openvman-role", b"admin"),
            (b"x-openvman-project-id", b"forged-project"),
            (b"x-internal-token", b"forged-token"),
            (b"authorization", b"Bearer end-user-token"),
            (b"cookie", b"openvman_session=end-user-token"),
            (b"x-trace-id", b"trace-1"),
        ]
    )
    current = MagicMock()
    current.user.id = "verified-user"
    current.user.role = AccountRole.USER

    with patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()):
        headers = _trusted_upstream_headers(
            request,
            current=current,
            project_id="verified-project",
        )

    assert headers["X-Internal-Token"] == "internal-secret"
    assert headers["X-OpenVMan-User-ID"] == "verified-user"
    assert headers["X-OpenVMan-Role"] == "user"
    assert headers["X-OpenVMan-Project-ID"] == "verified-project"
    assert headers["x-trace-id"] == "trace-1"
    assert "forged-user" not in headers.values()
    assert "forged-project" not in headers.values()
    assert "forged-token" not in headers.values()
    assert "authorization" not in headers
    assert "cookie" not in headers


def test_trusted_headers_do_not_invent_default_project() -> None:
    from app.brain_proxy import _trusted_upstream_headers

    request = _request_with_headers([])
    current = MagicMock()
    current.user.id = "verified-user"
    current.user.role = AccountRole.USER

    with patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()):
        headers = _trusted_upstream_headers(
            request,
            current=current,
            project_id=None,
        )

    assert "X-OpenVMan-Project-ID" not in headers


def test_backend_openapi_lists_explicit_brain_routes(client: TestClient):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/health" in paths
    assert "/api/v1/chat" in paths
    assert "/api/v1/chat/stream" in paths
    assert "/api/v1/chat/accept" in paths
    assert "/api/v1/knowledge/upload" in paths
    assert "/api/v1/knowledge/document/meta" in paths
    assert "/api/v1/knowledge/note" in paths
    assert "/api/v1/sessions/export" in paths


def test_project_content_writes_require_edit_access() -> None:
    from app.brain_proxy import _project_access

    assert _project_access("knowledge/document", "PUT") is ResourceAccess.EDIT
    assert _project_access("personas", "POST") is ResourceAccess.EDIT
    assert _project_access("skills/example", "DELETE") is ResourceAccess.EDIT
    assert _project_access("tools/example", "PATCH") is ResourceAccess.EDIT
    assert _project_access("memories/maintain", "POST") is ResourceAccess.EDIT
    assert _project_access("dreaming/run", "POST") is ResourceAccess.EDIT
    assert _project_access("sessions/export", "GET") is ResourceAccess.EDIT
    assert _project_access("sessions/export", "POST") is ResourceAccess.EDIT
    assert _project_access("sessions/s1", "DELETE") is ResourceAccess.EDIT
    assert _project_access("knowledge/document", "GET") is ResourceAccess.READ
    assert _project_access("chat/accept", "POST") is ResourceAccess.READ


@pytest.mark.parametrize(
    ("granted", "expected_status"),
    [(True, 200), (False, 404)],
)
@pytest.mark.parametrize("path", ["knowledge/document", "chat/accept"])
def test_portal_user_can_only_forward_granted_project_edits(
    granted: bool,
    expected_status: int,
    path: str,
) -> None:
    from app.brain_proxy import router

    app = FastAPI()
    app.include_router(router)
    current = _portal_current()

    def current_account(request: Request) -> CurrentAccount:
        request.state.current_account = current
        return current

    app.dependency_overrides[get_current_account] = current_account
    runtime = MagicMock()
    runtime.resources.get.return_value = MagicMock(owner_user_id="admin-user")
    runtime.resources.has_grant.return_value = granted
    upstream = _make_response()
    mock_client = MagicMock()
    mock_client.build_request.return_value = "request"
    mock_client.send = AsyncMock(return_value=upstream)

    with (
        patch("app.brain_proxy.get_auth_runtime", return_value=runtime),
        patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
        patch("app.brain_proxy._http.get", return_value=mock_client),
        TestClient(app) as isolated_client,
    ):
        response = isolated_client.request(
            "POST" if path == "chat/accept" else "PUT",
            f"/api/v1/{path}?project_id=project-a",
            json={"project_id": "project-a", "session_id": "s1",
                  "turn_id": "t1", "turn_revision": 2,
                  "path": "knowledge/a.md", "content": "updated"},
        )

    assert response.status_code == expected_status
    assert mock_client.send.await_count == (1 if granted else 0)


def test_chat_accept_requires_login():
    from app.brain_proxy import router

    app = FastAPI()
    app.include_router(router)
    with patch("app.brain_proxy._http.get") as upstream, TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/accept",
            json={"project_id": "p1", "session_id": "s1",
                  "turn_id": "t1", "turn_revision": 1},
        )
    assert response.status_code == 401
    upstream.assert_not_called()


def test_explicit_brain_routes_still_forward_options(client: TestClient):
    upstream = _make_response(body=b"", content_type="text/plain")
    mock_client = MagicMock()
    mock_client.build_request = MagicMock(return_value="request")
    mock_client.send = AsyncMock(return_value=upstream)

    with (
        patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
        patch("app.brain_proxy._http.get", return_value=mock_client),
    ):
        response = client.options("/api/v1/health")

    assert response.status_code == 200
    build_kwargs = mock_client.build_request.call_args.kwargs
    assert build_kwargs["method"] == "OPTIONS"
    assert build_kwargs["url"] == "http://brain:8100/brain/health"


def test_gateway_brain_proxy_returns_502_when_upstream_disconnects(client: TestClient):
    mock_client = MagicMock()
    mock_client.build_request = MagicMock(return_value="request")
    mock_client.send = AsyncMock(side_effect=httpx.RemoteProtocolError("Server disconnected without sending a response."))

    with (
        patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
        patch("app.brain_proxy._http.get", return_value=mock_client),
    ):
        response = client.get("/api/v1/health")

    assert response.status_code == 502
    assert response.json() == {"error": "brain upstream disconnected"}


def test_gateway_brain_proxy_returns_504_on_timeout(client: TestClient):
    mock_client = MagicMock()
    mock_client.build_request = MagicMock(return_value="request")
    mock_client.send = AsyncMock(side_effect=httpx.ReadTimeout("Request timed out."))

    with (
        patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
        patch("app.brain_proxy._http.get", return_value=mock_client),
    ):
        response = client.get("/api/v1/health")

    assert response.status_code == 504
    assert response.json() == {"error": "brain request timeout"}


def test_gateway_brain_proxy_returns_504_on_read_body_timeout(client: TestClient):
    upstream = MagicMock()
    upstream.status_code = 200
    upstream.headers = {"content-type": "application/json"}
    upstream.aread = AsyncMock(side_effect=httpx.ReadTimeout("Read timed out during body read."))
    upstream.aclose = AsyncMock()
    upstream.aiter_bytes = MagicMock()

    mock_client = MagicMock()
    mock_client.build_request = MagicMock(return_value="request")
    mock_client.send = AsyncMock(return_value=upstream)

    with (
        patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
        patch("app.brain_proxy._http.get", return_value=mock_client),
    ):
        response = client.get("/api/v1/health")

    assert response.status_code == 504
    assert response.json() == {"error": "brain request timeout"}
    upstream.aclose.assert_called_once()


def test_gateway_brain_proxy_returns_502_on_generic_request_error(client: TestClient):
    mock_client = MagicMock()
    mock_client.build_request = MagicMock(return_value="request")
    mock_client.send = AsyncMock(side_effect=httpx.RequestError("Some request error."))

    with (
        patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
        patch("app.brain_proxy._http.get", return_value=mock_client),
    ):
        response = client.get("/api/v1/health")

    assert response.status_code == 502
    assert response.json() == {"error": "brain request error"}


def test_catchall_proxy_blocks_backend_owned_usage_prefix() -> None:
    """/api/v1/usage/* must go through the Backend route that scopes accounts."""
    import asyncio

    from app.brain_proxy import proxy_to_brain

    request = _request_with_headers([])
    for path in ("usage", "usage/summary", "usage/events"):
        response = asyncio.run(proxy_to_brain(request, path, current=None))
        assert response.status_code == 404


def test_catchall_proxy_blocks_backups_prefix() -> None:
    """備份限 ROOT；一般帳號不能經 catch-all 直通 Brain 的備份端點。"""
    import asyncio

    from app.brain_proxy import proxy_to_brain

    request = _request_with_headers([])
    for path in ("backups", "backups/sessions"):
        response = asyncio.run(proxy_to_brain(request, path, current=None))
        assert response.status_code == 404


def test_readable_but_not_editable_project_says_403(monkeypatch) -> None:
    # 2026-10-14：一般帳號刪對話回 404，串接方以為對話不存在；看得到的專案改成明說沒權限。
    from datetime import datetime, timezone

    from app.auth.models import ResourceType, ResourceVisibility
    from app.auth.runtime import get_auth_runtime
    from tests.api.test_main import _authenticated_client, _load_main

    module, _ = _load_main(monkeypatch)
    _authenticated_client(module)  # admin 建立並擁有 default 專案
    user_client, _ = _authenticated_client(module, admin=False)
    runtime = get_auth_runtime()
    admin = runtime.users.get_by_username("test-admin")
    user = runtime.users.get_by_username("test-user")
    runtime.resources.register(
        resource_type=ResourceType.PROJECT, resource_id="hidden",
        owner_user_id=admin.id, visibility=ResourceVisibility.PRIVATE,
    )
    with runtime.database.transaction(write=True) as connection:
        connection.execute(
            "INSERT INTO resource_grants(grantee_user_id, resource_type, resource_id,"
            " granted_by, created_at) VALUES (?, 'project', 'default', ?, ?)",
            (user.id, admin.id, datetime.now(timezone.utc).isoformat()),
        )

    granted = user_client.delete("/api/v1/sessions/s-1", params={"project_id": "default"})
    hidden = user_client.delete("/api/v1/sessions/s-1", params={"project_id": "hidden"})

    assert granted.status_code == 403
    assert hidden.status_code == 404


def test_missing_or_conflicting_project_id_says_422(monkeypatch) -> None:
    # VH-371：缺 project_id 原本回 404「Resource not found」，串接方以為專案不存在，
    # 而且連空訊息的欄位驗證都到不了。缺欄位與兩處不一致是請求格式問題，改回 422。
    from tests.api.test_main import _authenticated_client, _load_main

    module, _ = _load_main(monkeypatch)
    client, _ = _authenticated_client(module)

    missing = client.post("/api/v1/chat", json={"message": ""})
    conflicting = client.post(
        "/api/v1/chat",
        params={"project_id": "default"},
        json={"message": "hi", "project_id": "other"},
    )
    hidden = client.post(
        "/api/v1/chat", json={"message": "hi", "project_id": "no-such-project"},
    )

    assert missing.status_code == 422
    assert missing.json() == {"detail": "project_id is required"}
    assert conflicting.status_code == 422
    assert conflicting.json() == {
        "detail": "project_id in query and body must match",
    }
    assert hidden.status_code == 404

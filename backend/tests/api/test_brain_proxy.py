"""Tests for backend brain proxy facade routes."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.auth.models import AccountRole


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
            "path": "/api/search",
            "raw_path": b"/api/search",
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
        response = client.get("/api/health?project_id=default")

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
    assert "/api/health" in paths
    assert "/api/chat" in paths
    assert "/api/knowledge/upload" in paths
    assert "/api/knowledge/document/meta" in paths
    assert "/api/knowledge/note" in paths


def test_explicit_brain_routes_still_forward_options(client: TestClient):
    upstream = _make_response(body=b"", content_type="text/plain")
    mock_client = MagicMock()
    mock_client.build_request = MagicMock(return_value="request")
    mock_client.send = AsyncMock(return_value=upstream)

    with (
        patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
        patch("app.brain_proxy._http.get", return_value=mock_client),
    ):
        response = client.options("/api/health")

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
        response = client.get("/api/health")

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
        response = client.get("/api/health")

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
        response = client.get("/api/health")

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
        response = client.get("/api/health")

    assert response.status_code == 502
    assert response.json() == {"error": "brain request error"}

"""Tests for backend brain proxy facade routes."""

from __future__ import annotations

from collections.abc import AsyncIterator
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _mock_cfg():
    return MagicMock(brain_url="http://brain:8100")


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
        patch("app.brain_proxy._get_client", return_value=mock_client),
    ):
        response = client.get("/api/health?project_id=default")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_client.build_request.assert_called_once()
    build_kwargs = mock_client.build_request.call_args.kwargs
    assert build_kwargs["url"] == "http://brain:8100/brain/health?project_id=default"


def test_gateway_brain_proxy_closes_sse_upstream(client: TestClient):
    async def _aiter_bytes() -> AsyncIterator[bytes]:
        yield b"event: token\ndata: {\"token\":\"hi\"}\n\n"

    upstream = _make_response(content_type="text/event-stream")
    upstream.aiter_bytes = _aiter_bytes
    mock_client = MagicMock()
    mock_client.build_request = MagicMock(return_value="request")
    mock_client.send = AsyncMock(return_value=upstream)

    with (
        patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
        patch("app.brain_proxy._get_client", return_value=mock_client),
    ):
        with client.stream("GET", "/api/chat/stream") as response:
            body = b"".join(response.iter_bytes())

    assert response.status_code == 200
    assert body == b"event: token\ndata: {\"token\":\"hi\"}\n\n"
    upstream.aclose.assert_awaited_once()


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
        patch("app.brain_proxy._get_client", return_value=mock_client),
    ):
        response = client.options("/api/health")

    assert response.status_code == 200
    build_kwargs = mock_client.build_request.call_args.kwargs
    assert build_kwargs["method"] == "OPTIONS"
    assert build_kwargs["url"] == "http://brain:8100/brain/health"

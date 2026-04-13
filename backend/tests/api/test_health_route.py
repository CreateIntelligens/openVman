"""Tests for backend health routes."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_singletons():
    from app.config import get_tts_config
    from app.gateway.temp_storage import reset_temp_storage

    get_tts_config.cache_clear()
    reset_temp_storage()
    yield
    get_tts_config.cache_clear()
    reset_temp_storage()


@pytest.fixture()
def client(tmp_path):
    env = {
        "GATEWAY_TEMP_DIR": str(tmp_path),
        "GATEWAY_TEMP_DIR_MAX_MB": "100",
        "DOCLING_SERVE_URL": "http://docling-serve:5001",
        "TTS_INDEXTTS_URL": "http://index-tts:8080",
    }
    with patch.dict(os.environ, env, clear=False):
        from app.config import get_tts_config

        get_tts_config.cache_clear()
        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def _mock_health_client(responses: dict[str, dict] | None = None):
    """Return a patch context that injects a mock httpx client into app.main._health_client."""

    async def _fake_get(url, **kwargs):
        resp = MagicMock(spec=httpx.Response)
        if responses and any(url.endswith(suffix) for suffix in responses):
            for suffix, body in responses.items():
                if url.endswith(suffix):
                    resp.json.return_value = body
                    resp.status_code = 200
                    return resp
        resp.json.return_value = {"status": "healthy"}
        resp.status_code = 200
        return resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(side_effect=_fake_get)
    return patch(
        "app.routes.admin._health_http",
        MagicMock(
            get=lambda: mock_client,
            close=AsyncMock(return_value=None),
        ),
    )


class TestHealthzOk:
    def test_healthz_ok_when_redis_connected(self, client: TestClient):
        with (
            patch("app.routes.admin.redis_available", new_callable=AsyncMock, return_value=True),
            _mock_health_client({"/brain/health": {"status": "ok"}}),
        ):
            resp = client.get("/healthz")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "tts-router"
        assert body["dependencies"]["redis"]["status"] == "ok"
        assert body["dependencies"]["temp_storage"]["status"] == "ok"
        assert body["dependencies"]["docling-serve"]["status"] == "healthy"
        assert "timestamp" in body

    def test_healthz_includes_downstream_brain(self, client: TestClient):
        with (
            patch("app.routes.admin.redis_available", new_callable=AsyncMock, return_value=True),
            _mock_health_client({"/brain/health": {"status": "ok"}}),
        ):
            resp = client.get("/healthz")

        body = resp.json()
        assert "brain" in body["dependencies"]
        assert body["dependencies"]["brain"]["status"] == "ok"
        assert "docling-serve" in body["dependencies"]


class TestHealthzDegraded:
    def test_healthz_degraded_when_redis_down(self, client: TestClient):
        with (
            patch("app.routes.admin.redis_available", new_callable=AsyncMock, return_value=False),
            _mock_health_client({"/brain/health": {"status": "ok"}}),
        ):
            resp = client.get("/healthz")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["dependencies"]["redis"]["status"] == "error"
        assert body["dependencies"]["redis"]["connection"] == "disconnected"

    def test_healthz_degraded_when_downstream_unreachable(self, client: TestClient):
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with (
            patch("app.routes.admin.redis_available", new_callable=AsyncMock, return_value=True),
            patch(
                "app.routes.admin._health_http",
                MagicMock(
                    get=lambda: mock_client,
                    close=AsyncMock(return_value=None),
                ),
            ),
        ):
            resp = client.get("/healthz")

        body = resp.json()
        assert body["status"] == "degraded"
        assert body["dependencies"]["brain"]["status"] == "unreachable"
        assert body["dependencies"]["docling-serve"]["status"] == "unreachable"

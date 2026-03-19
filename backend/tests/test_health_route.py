"""Tests for GET /health route."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

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
    }
    with patch.dict(os.environ, env, clear=False):
        from app.config import get_tts_config

        get_tts_config.cache_clear()
        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestHealthRedisUp:
    def test_health_ok_when_redis_connected(self, client: TestClient):
        with patch("app.gateway.routes.redis_available", new_callable=AsyncMock, return_value=True):
            resp = client.get("/health")
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "ok"
            assert body["redis"] == "connected"
            assert body["temp_storage"]["ok"] is True


class TestHealthRedisDown:
    def test_health_degraded_when_redis_down(self, client: TestClient):
        with patch("app.gateway.routes.redis_available", new_callable=AsyncMock, return_value=False):
            resp = client.get("/health")
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "degraded"
            assert body["redis"] == "disconnected"

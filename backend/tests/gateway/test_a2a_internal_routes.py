"""Unit tests for Backend internal A2A facade routes."""

from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.config import TTSRouterConfig


@pytest.mark.asyncio
async def test_internal_a2a_routes_require_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. No token -> 403 or 503
        resp = await client.get("/api/v1/internal/a2a/peers")
        assert resp.status_code in (403, 503)

        # 2. Invalid token -> 403
        resp = await client.get(
            "/api/v1/internal/a2a/peers",
            headers={"X-Internal-Token": "invalid-secret"},
        )
        assert resp.status_code in (403, 503)


@pytest.mark.asyncio
async def test_internal_a2a_disabled_response():
    transport = ASGITransport(app=app)
    cfg = TTSRouterConfig(
        a2a_enabled=False,
        gateway_internal_token="valid-token-123",
    )

    with patch("app.internal_routes.get_tts_config", return_value=cfg):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/internal/a2a/peers",
                headers={"X-Internal-Token": "valid-token-123"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["enabled"] is False
            assert data["peers"] == []


@pytest.mark.asyncio
async def test_internal_a2a_send_task_hop_limit():
    transport = ASGITransport(app=app)
    cfg = TTSRouterConfig(
        a2a_enabled=True,
        gateway_internal_token="valid-token-123",
        a2a_max_delegation_hops=3,
    )

    with patch("app.internal_routes.get_tts_config", return_value=cfg):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/internal/a2a/tasks",
                json={
                    "target_agent_id": "target-1",
                    "message": "Hello",
                    "hop_count": 5,  # Exceeds max 3
                },
                headers={"X-Internal-Token": "valid-token-123"},
            )
            assert resp.status_code == 400
            assert "Delegation hop limit exceeded" in resp.json()["detail"]

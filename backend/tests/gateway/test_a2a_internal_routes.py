"""Unit tests for Backend internal A2A facade routes."""

from pathlib import Path
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.config import TTSRouterConfig
from app.gateway.a2a_bridge import A2ABridgeDaemon
from app.gateway.a2a_client import A2ARateLimitError
from app.gateway.a2a_queue import A2AWorkQueue
from app.gateway.a2a_store import A2ACredentialStore, A2ACredentials, compute_key_fingerprint


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


@pytest.mark.asyncio
async def test_internal_a2a_non_leader_serves_outbound_routes_from_shared_store(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BACKEND_WORKERS", raising=False)
    creds_file = tmp_path / "creds.json"
    queue_file = tmp_path / "work.db"
    enc_key = "test-secret"
    hub_url = "https://hub.example"
    hub_key = "circle-secret"
    store = A2ACredentialStore(creds_file, encryption_key=enc_key)
    store.save(
        A2ACredentials(
            agentId="agent-shared",
            agentToken="tok-shared",
            circleId="circle-secret",
            hubUrl=hub_url,
            hubKeyFingerprint=compute_key_fingerprint(hub_key, enc_key),
        )
    )

    cfg = TTSRouterConfig(
        a2a_enabled=True,
        a2a_hub_url=hub_url,
        a2a_hub_key=hub_key,
        a2a_allow_group_broadcast=True,
        a2a_credentials_path=str(creds_file),
        a2a_credentials_encryption_key=enc_key,
        a2a_queue_db_path=str(queue_file),
        gateway_internal_token="valid-token-123",
        backend_workers=4,
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=A2AWorkQueue(queue_file))
    assert daemon.is_leader is False

    seen: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("Authorization", "")))
        if request.url.path == "/hub/v1/agents":
            return httpx.Response(200, json=[{"agentId": "peer-1"}])
        if request.url.path == "/hub/v1/agents/peer-1/tasks":
            return httpx.Response(200, json={"status": "QUEUED"})
        if request.url.path == "/hub/v1/groups/grp-1/messages":
            return httpx.Response(200, json={"status": "BROADCAST"})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mock_http:
        client = daemon.get_outbound_client()
        assert client is not None
        client._client = mock_http
        client._external_client = mock_http

        transport = ASGITransport(app=app)
        with (
            patch("app.internal_routes.get_tts_config", return_value=cfg),
            patch("app.gateway.a2a_bridge.get_a2a_bridge_daemon", return_value=daemon),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as api:
                headers = {"X-Internal-Token": "valid-token-123"}
                r1 = await api.get("/api/v1/internal/a2a/peers", headers=headers)
                assert r1.status_code == 200
                assert r1.headers.get("X-OpenVMan-Worker-ID") == daemon.worker_id
                assert r1.json()["peers"] == [{"agentId": "peer-1"}]
                assert r1.json()["is_leader"] is False
                assert r1.json()["worker_id"] == daemon.worker_id

                r2 = await api.post(
                    "/api/v1/internal/a2a/tasks",
                    json={"target_agent_id": "peer-1", "message": "hi"},
                    headers=headers,
                )
                assert r2.status_code == 200
                assert r2.headers.get("X-OpenVMan-Worker-ID") == daemon.worker_id
                assert r2.json()["success"] is True
                assert "worker_id" not in r2.json()

                r3 = await api.post(
                    "/api/v1/internal/a2a/groups/messages",
                    json={"group_id": "grp-1", "message": "all"},
                    headers=headers,
                )
                assert r3.status_code == 200
                assert r3.headers.get("X-OpenVMan-Worker-ID") == daemon.worker_id
                assert r3.json()["success"] is True
                assert "worker_id" not in r3.json()

    assert seen == [
        ("GET", "/hub/v1/agents", "Bearer tok-shared"),
        ("POST", "/hub/v1/agents/peer-1/tasks", "Bearer tok-shared"),
        ("POST", "/hub/v1/groups/grp-1/messages", "Bearer tok-shared"),
    ]


@pytest.mark.asyncio
async def test_internal_a2a_returns_503_without_credentials_and_429_on_rate_limit(tmp_path: Path):
    cfg = TTSRouterConfig(
        a2a_enabled=True,
        a2a_hub_url="https://hub.example",
        a2a_hub_key="circle-secret",
        a2a_credentials_path=str(tmp_path / "missing-creds.json"),
        a2a_credentials_encryption_key="test",
        a2a_queue_db_path=str(tmp_path / "work.db"),
        gateway_internal_token="valid-token-123",
    )
    daemon = A2ABridgeDaemon(
        config=cfg,
        store=A2ACredentialStore(cfg.a2a_credentials_path, "test"),
        queue=A2AWorkQueue(cfg.a2a_queue_db_path),
    )

    transport = ASGITransport(app=app)
    with (
        patch("app.internal_routes.get_tts_config", return_value=cfg),
        patch("app.gateway.a2a_bridge.get_a2a_bridge_daemon", return_value=daemon),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as api:
            headers = {"X-Internal-Token": "valid-token-123"}
            resp_503 = await api.get("/api/v1/internal/a2a/peers", headers=headers)
            assert resp_503.status_code == 503
            assert "credentials" in resp_503.json()["detail"].lower()

            with patch.object(
                daemon,
                "call_outbound",
                new_callable=AsyncMock,
                side_effect=A2ARateLimitError(retry_after=12, max_calls=5),
            ):
                resp_429 = await api.post(
                    "/api/v1/internal/a2a/tasks",
                    json={"target_agent_id": "peer-1", "message": "hi"},
                    headers=headers,
                )
                assert resp_429.status_code == 429
                assert resp_429.headers.get("Retry-After") == "12"
                assert resp_429.headers.get("X-OpenVMan-Worker-ID") == daemon.worker_id

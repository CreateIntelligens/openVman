"""Unit tests for A2AClient with mocked HTTP transport."""

import json
import httpx
import pytest

from app.gateway.a2a_client import A2AClient
from app.gateway.a2a_store import A2ACredentials, compute_key_hash


@pytest.mark.asyncio
async def test_a2a_client_register():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/hub/v1/agents/register"
        assert request.headers.get("X-Hub-Key") == "test-private-circle"
        data = json.loads(request.content.decode())
        assert data["displayName"] == "openVman"
        assert data["providerFamily"] == "openvman"

        resp_body = {
            "identity": {
                "hubId": "public",
                "agentId": "agent-test-123",
                "circleId": "test-private-circle",
                "agentToken": "secret-token-xyz",
                "expiresAt": "2027-01-01T00:00:00Z",
            }
        }
        return httpx.Response(200, json=resp_body)

    mock_transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=mock_transport) as mock_http:
        client = A2AClient(
            hub_url="https://a2a.david888.com",
            hub_key="test-private-circle",
            http_client=mock_http,
        )
        creds = await client.register(display_name="openVman")
        assert creds.agent_id == "agent-test-123"
        assert creds.agent_token == "secret-token-xyz"
        assert creds.circle_id == "test-private-circle"
        assert creds.hub_key_hash == compute_key_hash("test-private-circle")


@pytest.mark.asyncio
async def test_a2a_client_instant_ack():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/hub/v1/agents/agent-123/inbox/42/ack"
        assert request.headers.get("X-Agent-ID") == "agent-123"
        assert request.headers.get("Authorization") == "Bearer secret-abc"
        return httpx.Response(204)

    mock_transport = httpx.MockTransport(handler)
    creds = A2ACredentials(
        agentId="agent-123",
        agentToken="secret-abc",
        circleId="ai360",
        hubUrl="https://a2a.david888.com",
        hubKeyHash=compute_key_hash("ai360"),
    )
    async with httpx.AsyncClient(transport=mock_transport) as mock_http:
        client = A2AClient(
            hub_url="https://a2a.david888.com",
            credentials=creds,
            http_client=mock_http,
        )
        ok = await client.acknowledge_task(sequence=42)
        assert ok is True


@pytest.mark.asyncio
async def test_a2a_client_send_task():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/hub/v1/agents/target-agent/tasks"
        assert request.headers.get("X-Agent-ID") == "agent-123"
        data = json.loads(request.content.decode())
        assert data["message"] == "Hello from openVman"
        assert "taskId" in data
        return httpx.Response(200, json={"status": "QUEUED", "taskId": data["taskId"]})

    mock_transport = httpx.MockTransport(handler)
    creds = A2ACredentials(
        agentId="agent-123",
        agentToken="secret-abc",
        circleId="ai360",
        hubUrl="https://a2a.david888.com",
        hubKeyHash=compute_key_hash("ai360"),
    )
    async with httpx.AsyncClient(transport=mock_transport) as mock_http:
        client = A2AClient(
            hub_url="https://a2a.david888.com",
            credentials=creds,
            http_client=mock_http,
        )
        res = await client.send_task(target_agent_id="target-agent", message="Hello from openVman")
        assert res["status"] == "QUEUED"


@pytest.mark.asyncio
async def test_a2a_client_list_peers():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/hub/v1/agents"
        assert request.url.params.get("state") == "online"
        return httpx.Response(200, json=[
            {"agentId": "peer-1", "displayName": "OpenClaw", "state": "ONLINE"}
        ])

    mock_transport = httpx.MockTransport(handler)
    creds = A2ACredentials(
        agentId="agent-123",
        agentToken="secret-abc",
        circleId="ai360",
        hubUrl="https://a2a.david888.com",
        hubKeyHash=compute_key_hash("ai360"),
    )
    async with httpx.AsyncClient(transport=mock_transport) as mock_http:
        client = A2AClient(
            hub_url="https://a2a.david888.com",
            credentials=creds,
            http_client=mock_http,
        )
        peers = await client.list_peers(state="online")
        assert len(peers) == 1
        assert peers[0]["displayName"] == "OpenClaw"

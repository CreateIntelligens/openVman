from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import internal_routes
from app.gateway import forward


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(internal_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _payload() -> dict[str, object]:
    return {
        "trace_id": "trace-timeout",
        "session_id": "session-timeout",
        "enriched_context": [{"type": "camera_snapshot", "content": "有人靠近櫃台"}],
        "media_refs": [],
    }


def test_internal_enrich_returns_504_when_brain_times_out():
    mock_client = SimpleNamespace(
        post=AsyncMock(side_effect=httpx.ReadTimeout("brain enrich timeout"))
    )

    with (
        patch.object(
            internal_routes,
            "get_tts_config",
            return_value=SimpleNamespace(
                brain_url="http://brain:8100",
                gateway_internal_token="test-token",
            ),
        ),
        patch.object(internal_routes._http, "get", return_value=mock_client),
        _client() as client,
    ):
        response = client.post(
            "/internal/enrich",
            json=_payload(),
            headers={internal_routes.INTERNAL_TOKEN_HEADER: "test-token"},
        )

    assert response.status_code == 504
    assert response.json() == {"detail": "brain enrich timeout"}


def test_internal_enrich_brain_timeout_is_shorter_than_gateway_forward_timeout():
    assert internal_routes._http._timeout.read < forward._http._timeout.read

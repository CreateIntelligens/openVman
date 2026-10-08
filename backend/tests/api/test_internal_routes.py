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
            "/api/v1/internal/enrich",
            json=_payload(),
            headers={internal_routes.INTERNAL_TOKEN_HEADER: "test-token"},
        )

    assert response.status_code == 504
    assert response.json() == {"detail": "brain enrich timeout"}
    assert mock_client.post.await_args.kwargs["headers"] == {
        internal_routes.INTERNAL_TOKEN_HEADER: "test-token"
    }


def test_internal_enrich_fails_closed_when_token_is_not_configured():
    with (
        patch.object(
            internal_routes,
            "get_tts_config",
            return_value=SimpleNamespace(
                brain_url="http://brain:8100",
                gateway_internal_token="",
            ),
        ),
        _client() as client,
    ):
        response = client.post("/api/v1/internal/enrich", json=_payload())

    assert response.status_code == 503
    assert response.json() == {"detail": "internal token is not configured"}


def test_internal_enrich_brain_timeout_is_shorter_than_gateway_forward_timeout():
    assert internal_routes._http._timeout.read < forward._http._timeout.read


def test_internal_decision_provider_route_requires_token_and_returns_enabled_hops(tmp_path):
    from app.auth.runtime import build_auth_runtime
    from app.config import TTSRouterConfig

    runtime = build_auth_runtime(TTSRouterConfig(
        _env_file=None,
        env="dev",
        session_jwt_secret="test-only-session-secret-for-tests-32",
        decision_provider_encryption_secret="provider-encryption-secret-for-test-32-bytes",
        auth_database_path=str(tmp_path / "accounts.db"),
    ))
    actor = runtime.users.create_root(username="ai360", password_hash="hash")
    runtime.decision_providers.update(
        ("openai", "jev", "clef-backup", "clef-primary"),
        ("openai", "clef-primary"),
        credentials={"openai": "openai-secret"},
        actor_id=actor.id,
    )
    from app.auth import runtime as auth_runtime
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(internal_routes.router)
    app.dependency_overrides[auth_runtime.get_auth_runtime] = lambda: runtime

    with (
        patch.object(
            internal_routes,
            "get_tts_config",
            return_value=SimpleNamespace(gateway_internal_token="test-token"),
        ),
        patch.object(auth_runtime, "get_auth_runtime", return_value=runtime),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        rejected = client.get("/api/v1/internal/decision-providers")
        response = client.get(
            "/api/v1/internal/decision-providers",
            headers={internal_routes.INTERNAL_TOKEN_HEADER: "test-token"},
        )

    assert rejected.status_code == 403
    assert response.status_code == 200
    assert response.json()["order"] == ["openai", "clef-primary"]
    assert [hop["id"] for hop in response.json()["providers"]] == ["openai", "clef-primary"]
    assert response.json()["providers"][0]["api_key"] == "openai-secret"


def test_decision_provider_runtime_route_bypasses_user_auth_but_keeps_internal_auth():
    from app.auth.middleware import is_auth_bypass_path

    assert is_auth_bypass_path("/api/v1/internal/decision-providers") is True

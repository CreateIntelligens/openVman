from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from safety import internal_auth


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        internal_auth,
        "get_settings",
        lambda: SimpleNamespace(gateway_internal_token="internal-secret"),
    )


def _client() -> TestClient:
    from routes.health import router as health_router
    from routes.protocol import router as protocol_router

    app = FastAPI()
    app.include_router(health_router)
    app.include_router(protocol_router)
    return TestClient(app)


def test_public_health_routes_do_not_require_internal_token() -> None:
    with _client() as client:
        response = client.get("/brain/health")

    assert response.status_code == 200


def test_protected_brain_route_rejects_missing_and_wrong_internal_token() -> None:
    with _client() as client:
        missing = client.post(
            "/brain/protocol/validate",
            json={"direction": "client_to_server", "payload": {}},
        )
        wrong = client.post(
            "/brain/protocol/validate",
            headers={"X-Internal-Token": "wrong"},
            json={"direction": "client_to_server", "payload": {}},
        )

    assert missing.status_code == 403
    assert wrong.status_code == 403


def test_protected_brain_route_accepts_configured_internal_token() -> None:
    with _client() as client:
        response = client.post(
            "/brain/protocol/validate",
            headers={"X-Internal-Token": "internal-secret"},
            json={
                "direction": "client_to_server",
                "payload": {"event": "client_interrupt"},
            },
        )

    assert response.status_code == 200

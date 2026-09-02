"""Retired paths fail hard; the new families reach their handlers.

Covers the hard-failure rule of the `api-route-families` spec: no redirect,
alias, or rewrite survives for a retired path, in any of the three families.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from tests.api.test_main import _authenticated_client, _load_main  # noqa: E402

# One representative retired path per family, with the method that used to
# serve it. `POST /api/chat` also proves the Brain proxy catch-all no longer
# claims the bare `/api` prefix.
RETIRED_PATHS = [
    ("POST", "/api/chat"),
    ("GET", "/characters"),
    ("POST", "/tts/stream"),
    ("GET", "/v1/tts/providers"),
    ("POST", "/uploads"),
    ("GET", "/admin/dlq"),
    ("GET", "/assets/x/01.webm"),
    ("GET", "/mascots/x/model.vrm"),
    ("GET", "/backgrounds/x/image.png"),
    ("GET", "/v1/usage/summary"),
    ("POST", "/documents/convert"),
    ("POST", "/internal/enrich"),
    ("POST", "/api/knowledge/upload"),
    ("GET", "/api/projects"),
    ("GET", "/api/avatar"),
    ("GET", "/api/backgrounds"),
    ("GET", "/api/avatar/mascots"),
    ("GET", "/api/vision/health"),
    ("GET", "/api/users"),
    ("POST", "/api/auth/login"),
    ("GET", "/openvman-avatar-sdk.js"),
    ("GET", "/sdk/runtime/OpenVmanAvatarRuntime.wasm"),
]

# Each new path must reach a handler. 404 would mean the route is missing;
# the handlers themselves may still answer 401/403/422/5xx depending on the
# request body and on whether the upstream Brain is reachable.
NEW_PATHS = [
    ("GET", "/api/v1/characters"),
    ("GET", "/api/v1/tts/providers"),
    ("GET", "/api/v1/dlq"),
    ("GET", "/api/v1/usage/summary"),
    ("GET", "/api/v1/projects"),
    ("GET", "/api/v1/avatar"),
    ("GET", "/api/v1/backgrounds"),
    ("GET", "/api/v1/avatar/mascots"),
    ("GET", "/api/v1/vision/health"),
    ("GET", "/api/v1/users"),
    ("GET", "/healthz"),
]


@pytest.fixture
def client(monkeypatch) -> TestClient:
    module, _ = _load_main(monkeypatch)
    authenticated, _ = _authenticated_client(module)
    return authenticated


@pytest.mark.parametrize(("method", "path"), RETIRED_PATHS)
def test_retired_path_returns_404(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path)
    assert response.status_code == 404


@pytest.mark.parametrize(("method", "path"), NEW_PATHS)
def test_new_path_reaches_a_handler(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path)
    assert response.status_code != 404


def test_retired_static_paths_lost_their_public_middleware_bypass(monkeypatch) -> None:
    module, _ = _load_main(monkeypatch)
    anonymous = TestClient(module.app, raise_server_exceptions=False)

    # `/assets/` used to be a public prefix, so an anonymous caller reached the
    # router. It is no longer in the allowlist, so the fail-closed middleware
    # rejects it before routing — never a redirect or an alias to /static.
    assert anonymous.get("/assets/x/01.webm").status_code == 401
    assert anonymous.get("/openvman-avatar-sdk.js").status_code == 401
    assert anonymous.get("/sdk/runtime/OpenVmanAvatarRuntime.wasm").status_code == 401


def test_static_character_family_is_public_and_others_require_auth(monkeypatch) -> None:
    module, _ = _load_main(monkeypatch)
    anonymous = TestClient(module.app, raise_server_exceptions=False)

    # Route-level policy answers 404 for an unknown public character, while
    # mascots and backgrounds stay behind the fail-closed middleware (401).
    assert anonymous.get("/static/characters/missing/01.webm").status_code == 404
    assert anonymous.get("/static/mascots/missing/model.vrm").status_code == 401
    assert anonymous.get("/static/backgrounds/missing/image.png").status_code == 401


def test_openai_audio_family_keeps_only_speech(client: TestClient) -> None:
    assert client.get("/v1/tts/providers").status_code == 404
    assert client.get("/v1/usage/events").status_code == 404
    assert client.post("/v1/audio/speech", json={"input": ""}).status_code != 404


def test_websocket_moved_under_the_api_family(monkeypatch) -> None:
    module, _ = _load_main(monkeypatch)
    authenticated, _ = _authenticated_client(module)

    with pytest.raises(Exception):
        with authenticated.websocket_connect("/ws/retired-client"):
            pass

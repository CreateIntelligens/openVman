"""Every scenario of the `embed-key-management` spec."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from tests.api.test_main import _authenticated_client, _load_main  # noqa: E402

KEY_ID_PATTERN = re.compile(r"^ovk_[a-z2-7]{24}$")
VALID_ORIGIN = "https://partner.example"


@pytest.fixture
def admin_client(monkeypatch):
    module, _ = _load_main(monkeypatch)
    client, _token = _authenticated_client(module)
    return module, client


def _create_payload(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "label": "Partner site",
        "project_id": "default",
        "allowed_origins": [VALID_ORIGIN],
    }
    payload.update(overrides)
    return payload


# --- Requirement: Administrator embed-key API -----------------------------


def test_create_returns_the_generated_key_and_creation_defaults(admin_client):
    _module, client = admin_client

    response = client.post("/api/v1/embed-keys", json=_create_payload())

    assert response.status_code == 201
    body = response.json()
    assert KEY_ID_PATTERN.match(body["key_id"]), body["key_id"]
    assert body["project_id"] == "default"
    assert body["allowed_origins"] == [VALID_ORIGIN]
    assert body["disabled"] is False
    assert body["rate_limit_per_minute"] == 60
    assert body["daily_request_quota"] == 1000
    assert body["requests_today"] == 0


def test_create_honours_supplied_limits_and_defaults(admin_client):
    _module, client = admin_client

    response = client.post(
        "/api/v1/embed-keys",
        json=_create_payload(
            default_character_id="aria",
            allowed_character_ids=["nova"],
            default_persona_id="host",
            default_tts_provider="indextts",
            default_tts_voice="hayley",
            rate_limit_per_minute=10,
            daily_request_quota=100,
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["default_character_id"] == "aria"
    assert body["allowed_character_ids"] == ["nova"]
    assert body["default_persona_id"] == "host"
    assert body["default_tts_provider"] == "indextts"
    assert body["default_tts_voice"] == "hayley"
    assert body["rate_limit_per_minute"] == 10
    assert body["daily_request_quota"] == 100


@pytest.mark.parametrize(
    "origin",
    ["*", "https://*.example.com", "partner.example", "//partner.example"],
)
def test_wildcard_or_schemeless_origin_is_refused(admin_client, origin):
    _module, client = admin_client

    response = client.post(
        "/api/v1/embed-keys",
        json=_create_payload(allowed_origins=[origin]),
    )

    assert response.status_code == 400
    assert client.get("/api/v1/embed-keys").json()["embed_keys"] == []


def test_origin_with_a_path_is_refused(admin_client):
    _module, client = admin_client

    response = client.post(
        "/api/v1/embed-keys",
        json=_create_payload(allowed_origins=["https://partner.example/widget"]),
    )

    assert response.status_code == 400


def test_empty_origin_list_is_rejected(admin_client):
    _module, client = admin_client

    response = client.post(
        "/api/v1/embed-keys",
        json=_create_payload(allowed_origins=[]),
    )

    assert response.status_code == 422


def test_missing_project_is_not_found(admin_client):
    _module, client = admin_client

    response = client.post(
        "/api/v1/embed-keys",
        json=_create_payload(project_id="no-such-project"),
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "field",
    ["rate_limit_per_minute", "daily_request_quota"],
)
def test_limits_below_one_are_rejected(admin_client, field):
    _module, client = admin_client

    response = client.post("/api/v1/embed-keys", json=_create_payload(**{field: 0}))

    assert response.status_code == 422


def test_list_reports_todays_request_count(admin_client):
    module, client = admin_client
    created = client.post("/api/v1/embed-keys", json=_create_payload()).json()

    from app.auth.runtime import get_auth_runtime

    get_auth_runtime().embed_keys.increment_daily(created["key_id"])

    listed = client.get("/api/v1/embed-keys").json()["embed_keys"]

    assert len(listed) == 1
    assert listed[0]["key_id"] == created["key_id"]
    assert listed[0]["requests_today"] == 1


def test_patch_applies_without_restart(admin_client):
    _module, client = admin_client
    created = client.post("/api/v1/embed-keys", json=_create_payload()).json()

    response = client.patch(
        f"/api/v1/embed-keys/{created['key_id']}",
        json={
            "label": "Renamed",
            "allowed_origins": ["https://other.example"],
            "rate_limit_per_minute": 5,
            "disabled": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["label"] == "Renamed"
    assert body["allowed_origins"] == ["https://other.example"]
    assert body["rate_limit_per_minute"] == 5
    assert body["disabled"] is True

    from app.auth.runtime import get_auth_runtime

    stored = get_auth_runtime().embed_keys.get(created["key_id"])
    assert stored.disabled is True
    assert stored.allowed_origins == ("https://other.example",)


def test_patch_rejects_a_wildcard_origin(admin_client):
    _module, client = admin_client
    created = client.post("/api/v1/embed-keys", json=_create_payload()).json()

    response = client.patch(
        f"/api/v1/embed-keys/{created['key_id']}",
        json={"allowed_origins": ["*"]},
    )

    assert response.status_code == 400


def test_patch_on_a_missing_key_is_not_found(admin_client):
    _module, client = admin_client

    response = client.patch(
        "/api/v1/embed-keys/ovk_missing",
        json={"label": "nope"},
    )

    assert response.status_code == 404


def test_delete_revokes_the_key_so_requests_are_unauthorized(admin_client):
    module, client = admin_client
    created = client.post("/api/v1/embed-keys", json=_create_payload()).json()

    deleted = client.delete(f"/api/v1/embed-keys/{created['key_id']}")

    assert deleted.status_code == 200
    assert client.get("/api/v1/embed-keys").json()["embed_keys"] == []

    anonymous = TestClient(module.app, raise_server_exceptions=False)
    response = anonymous.get(
        "/api/v1/characters",
        headers={"X-Embed-Key": created["key_id"], "Origin": VALID_ORIGIN},
    )
    assert response.status_code == 401


def test_delete_on_a_missing_key_is_not_found(admin_client):
    _module, client = admin_client

    assert client.delete("/api/v1/embed-keys/ovk_missing").status_code == 404


# --- Requirement: administrators only -------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/embed-keys"),
        ("POST", "/api/v1/embed-keys"),
        ("PATCH", "/api/v1/embed-keys/ovk_whatever"),
        ("DELETE", "/api/v1/embed-keys/ovk_whatever"),
    ],
)
def test_non_administrator_is_forbidden(monkeypatch, method, path):
    module, _ = _load_main(monkeypatch)
    client, _token = _authenticated_client(module, admin=False)

    response = client.request(method, path, json=_create_payload())

    assert response.status_code == 403


def test_generated_key_ids_are_unique_and_well_formed(admin_client):
    _module, client = admin_client

    key_ids = {
        client.post("/api/v1/embed-keys", json=_create_payload()).json()["key_id"]
        for _ in range(5)
    }

    assert len(key_ids) == 5
    assert all(KEY_ID_PATTERN.match(key_id) for key_id in key_ids)

"""Tests for same-origin admin embed key management endpoints."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.embed_keys import EmbedKeyStore
from app.routes import admin as admin_routes


def _client(tmp_path, monkeypatch):
    store = EmbedKeyStore(tmp_path / "embed_keys.json")
    monkeypatch.setattr(admin_routes, "_embed_key_store", store, raising=False)
    app = FastAPI()
    app.include_router(admin_routes.router)
    return TestClient(app), store


def test_admin_create_returns_secret_once_and_list_hides_it(tmp_path, monkeypatch):
    client, _store = _client(tmp_path, monkeypatch)

    created = client.post(
        "/api/admin/embed-keys",
        json={
            "tenant_id": "tenant-a",
            "allowed_domains": ["example.com"],
            "note": "demo",
        },
    )
    listed = client.get("/api/admin/embed-keys")

    assert created.status_code == 200
    created_body = created.json()
    assert created_body["secret"]
    assert created_body["record"]["tenant_id"] == "tenant-a"
    assert listed.status_code == 200
    list_body = listed.json()
    assert "secret" not in list_body["keys"][0]
    assert created_body["secret"] not in str(list_body)


def test_admin_updates_allowed_domains(tmp_path, monkeypatch):
    client, _store = _client(tmp_path, monkeypatch)
    created = client.post(
        "/api/admin/embed-keys",
        json={"tenant_id": "tenant-a", "allowed_domains": ["example.com"]},
    ).json()

    updated = client.patch(
        f"/api/admin/embed-keys/{created['record']['key_id']}",
        json={"allowed_domains": ["docs.example.com"], "note": "docs"},
    )

    assert updated.status_code == 200
    body = updated.json()
    assert body["allowed_domains"] == ["docs.example.com"]
    assert body["note"] == "docs"


def test_admin_disable_revokes_key(tmp_path, monkeypatch):
    client, store = _client(tmp_path, monkeypatch)
    created = client.post(
        "/api/admin/embed-keys",
        json={"tenant_id": "tenant-a", "allowed_domains": ["example.com"]},
    ).json()

    disabled = client.post(f"/api/admin/embed-keys/{created['record']['key_id']}/disable")

    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert store.get(created["secret"]) is None

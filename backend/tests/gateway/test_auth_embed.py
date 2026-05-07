"""Tests for public embed API key authentication."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.gateway.auth_embed import EmbedAuthMiddleware, EmbedRateLimiter
from app.gateway.embed_keys import EmbedKeyStore


class FakeClock:
    def __init__(self) -> None:
        self.current = 1_700_000_000.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def _client(tmp_path, *, limit_per_minute: int = 60):
    clock = FakeClock()
    store = EmbedKeyStore(tmp_path / "embed_keys.json", time_fn=clock)
    created = store.create(
        tenant_id="tenant-a",
        allowed_domains=["example.com"],
    )
    app = FastAPI()
    app.add_middleware(
        EmbedAuthMiddleware,
        store=store,
        rate_limiter=EmbedRateLimiter(limit_per_minute=limit_per_minute, time_fn=clock),
    )

    @app.get("/api/embed/ping")
    def api_ping(request: Request):
        auth = request.state.embed_auth
        return {"tenant_id": auth.tenant_id, "key_id": auth.key_id}

    @app.get("/embed/avatar")
    def embed_avatar():
        return {"static": True}

    @app.get("/api/internal")
    def internal_ping():
        return {"ok": True}

    return TestClient(app), created, store, clock


def test_authorization_bearer_allows_api_embed_request(tmp_path):
    client, created, _store, _clock = _client(tmp_path)

    resp = client.get(
        "/api/embed/ping",
        headers={
            "Authorization": f"Bearer {created.secret}",
            "Origin": "https://example.com",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "tenant_id": "tenant-a",
        "key_id": created.record.key_id,
    }


def test_query_api_key_allows_api_embed_request(tmp_path):
    client, created, _store, _clock = _client(tmp_path)

    resp = client.get(
        f"/api/embed/ping?api_key={created.secret}",
        headers={"Origin": "https://example.com"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "tenant_id": "tenant-a",
        "key_id": created.record.key_id,
    }


def test_missing_and_disabled_keys_return_masked_401(tmp_path):
    client, created, store, _clock = _client(tmp_path)

    missing = client.get("/api/embed/ping")
    assert missing.status_code == 401
    assert missing.json() == {"error": "unauthorized"}

    assert store.disable(created.record.key_id) is not None
    disabled = client.get(
        "/api/embed/ping",
        headers={
            "Authorization": f"Bearer {created.secret}",
            "Origin": "https://example.com",
        },
    )
    assert disabled.status_code == 401
    assert disabled.json() == {"error": "unauthorized"}


def test_origin_mismatch_returns_masked_403(tmp_path):
    client, created, _store, _clock = _client(tmp_path)

    resp = client.get(
        "/api/embed/ping",
        headers={
            "Authorization": f"Bearer {created.secret}",
            "Origin": "https://malicious.com",
        },
    )

    assert resp.status_code == 403
    assert resp.json() == {"error": "unauthorized"}
    assert "Access-Control-Allow-Origin" not in resp.headers


def test_static_embed_entry_is_not_authenticated_by_middleware(tmp_path):
    client, created, _store, _clock = _client(tmp_path)

    embed_resp = client.get("/embed/avatar")
    assert embed_resp.status_code == 200
    assert embed_resp.json() == {"static": True}

    api_resp = client.get(
        "/api/embed/ping",
        headers={"Authorization": f"Bearer {created.secret}"},
    )
    assert api_resp.status_code == 200


def test_allowed_origin_gets_cors_headers_from_backend(tmp_path):
    client, created, _store, _clock = _client(tmp_path)
    origin = "https://example.com"

    resp = client.get(
        "/api/embed/ping",
        headers={
            "Authorization": f"Bearer {created.secret}",
            "Origin": origin,
        },
    )

    assert resp.status_code == 200
    assert resp.headers["Access-Control-Allow-Origin"] == origin
    assert "Authorization" in resp.headers["Access-Control-Allow-Headers"]
    assert "Origin" in resp.headers["Vary"]


def test_preflight_with_query_key_uses_allowlist(tmp_path):
    client, created, _store, _clock = _client(tmp_path)

    allowed = client.options(
        f"/api/embed/ping?api_key={created.secret}",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    denied = client.options(
        f"/api/embed/ping?api_key={created.secret}",
        headers={
            "Origin": "https://malicious.com",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert allowed.status_code == 204
    assert allowed.headers["Access-Control-Allow-Origin"] == "https://example.com"
    assert denied.status_code == 403
    assert "Access-Control-Allow-Origin" not in denied.headers


def test_rate_limit_returns_429_with_retry_after(tmp_path):
    client, created, _store, _clock = _client(tmp_path, limit_per_minute=2)
    headers = {
        "Authorization": f"Bearer {created.secret}",
        "Origin": "https://example.com",
    }

    assert client.get("/api/embed/ping", headers=headers).status_code == 200
    assert client.get("/api/embed/ping", headers=headers).status_code == 200
    limited = client.get("/api/embed/ping", headers=headers)

    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert limited.json() == {"error": "rate_limited"}


def test_non_embed_paths_are_not_authenticated(tmp_path):
    client, _created, _store, _clock = _client(tmp_path)

    resp = client.get("/api/internal")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

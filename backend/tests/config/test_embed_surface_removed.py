from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_backend_does_not_register_public_embed_auth_or_routes() -> None:
    source = (BACKEND_ROOT / "app" / "main.py").read_text()

    assert "EmbedAuthMiddleware" not in source
    assert "routes_embed" not in source
    assert "embed_router" not in source
    assert "gateway_router" in source
    assert "brain_proxy_router" in source


def test_admin_router_does_not_expose_embed_key_management() -> None:
    source = (BACKEND_ROOT / "app" / "routes" / "admin.py").read_text()

    assert "embed_keys" not in source
    assert "/api/admin/embed-keys" not in source
    assert "/healthz" in source

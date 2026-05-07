"""End-to-end-style tests for public embed auth and chat."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.gateway.auth_embed import EmbedAuthMiddleware, EmbedRateLimiter
from app.gateway.embed_keys import EmbedKeyStore
from app.gateway import routes_embed


class FakeClock:
    def __init__(self) -> None:
        self.current = 1_700_000_000.0

    def __call__(self) -> float:
        return self.current


@pytest.mark.asyncio
async def test_embed_auth_and_chat_flow_with_httpx(tmp_path, monkeypatch):
    clock = FakeClock()
    store = EmbedKeyStore(tmp_path / "embed_keys.json", time_fn=clock)
    created = store.create(tenant_id="tenant-a", allowed_domains=["example.com"])
    proxy = AsyncMock(return_value=JSONResponse({"reply": "hello", "session_id": "s1"}))
    monkeypatch.setattr(routes_embed, "_proxy_to_brain", proxy)

    app = FastAPI()
    app.add_middleware(
        EmbedAuthMiddleware,
        store=store,
        rate_limiter=EmbedRateLimiter(time_fn=clock),
    )
    app.include_router(routes_embed.router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing = await client.post("/api/embed/chat", json={"message": "hi"})
        valid = await client.post(
            "/api/embed/chat",
            headers={
                "Authorization": f"Bearer {created.secret}",
                "Origin": "https://example.com",
            },
            json={"message": "hi"},
        )

    assert missing.status_code == 401
    assert missing.json() == {"error": "unauthorized"}
    assert valid.status_code == 200
    assert valid.json() == {"reply": "hello", "session_id": "s1"}
    assert proxy.await_count == 1

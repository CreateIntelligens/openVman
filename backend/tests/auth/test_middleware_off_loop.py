"""Authentication reads (SQLite, Redis) run off the event loop.

They are synchronous; on the loop, one slow auth DB read stalled every request
the worker was serving (11/24 and 11/26: all workers stuck 1-2 s at once).
"""

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth import middleware
from app.auth.middleware import FailClosedAuthMiddleware


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def test_authentication_does_not_run_on_the_event_loop(monkeypatch):
    seen = []

    def fake_authenticate(_request, _runtime):
        seen.append(_on_event_loop())
        raise HTTPException(status_code=401, detail="no")

    monkeypatch.setattr(middleware, "authenticate_request", fake_authenticate)
    app = FastAPI()

    @app.get("/api/v1/private")
    def private():
        return {"ok": True}

    app.add_middleware(FailClosedAuthMiddleware, runtime=SimpleNamespace(config=SimpleNamespace(cors_allowed_origins="")))
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/api/v1/private").status_code == 401
    assert seen == [False]

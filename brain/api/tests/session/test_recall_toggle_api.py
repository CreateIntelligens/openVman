from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from memory.session_store import SessionStore


def _client(store: SessionStore) -> TestClient:
    from routes.sessions import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides = {}
    return TestClient(app)


def test_recall_toggle_endpoint_persists_disable_enable(tmp_path, monkeypatch):
    from routes import sessions as sessions_routes

    store = SessionStore(db_path=str(tmp_path / "sessions.db"))
    store.get_or_create_session("s1", "default")

    monkeypatch.setattr(sessions_routes, "get_session_store", lambda project_id="default": store)
    monkeypatch.setattr(sessions_routes, "log_event", lambda *args, **kwargs: None)

    with _client(store) as client:
        disable = client.post("/brain/sessions/s1/recall-toggle", json={"disabled": True})
        enable = client.post("/brain/sessions/s1/recall-toggle", json={"disabled": False})

    assert disable.status_code == 200
    assert disable.json() == {"session_id": "s1", "recall_disabled": True}
    assert enable.status_code == 200
    assert enable.json() == {"session_id": "s1", "recall_disabled": False}
    assert store.is_recall_disabled("s1") is False

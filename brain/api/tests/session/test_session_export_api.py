from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from memory.session_store import SessionStore


def _client() -> TestClient:
    from config import get_settings
    from routes.sessions import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(
        app,
        headers={"X-Internal-Token": get_settings().gateway_internal_token},
    )


def test_export_sessions_applies_filters_and_sanitizes_metadata(
    tmp_path,
    monkeypatch,
):
    from routes import sessions as sessions_routes

    store = SessionStore(db_path=str(tmp_path / "sessions.db"))
    store.append_message("included", "default", "user", "apple question")
    store.append_message(
        "included",
        "default",
        "assistant",
        "answer",
        metadata={
            "privacy_warning": {"categories": ["email"], "counts": {"email": 1}},
            "response_time_s": 1.25,
            "internal_only": "do not export",
        },
    )
    store.append_message("other", "default", "user", "banana question")
    store.append_message("other-persona", "doctor", "user", "apple diagnosis")

    monkeypatch.setattr(
        sessions_routes,
        "get_session_store",
        lambda project_id="default": store,
    )

    with _client() as client:
        response = client.get(
            "/brain/sessions/export",
            params={
                "project_id": "project-a",
                "persona_id": "default",
                "search": "apple",
                "session_ids": "included,other,other-persona",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == "project-a"
    assert payload["persona_id"] == "default"
    assert payload["total_sessions"] == 1
    assert payload["total_messages"] == 2
    assert [session["session_id"] for session in payload["sessions"]] == [
        "included"
    ]
    assistant = payload["sessions"][0]["messages"][1]
    assert assistant["privacy_warning"]["categories"] == ["email"]
    assert assistant["response_time_s"] == 1.25
    assert "metadata" not in assistant
    assert "internal_only" not in assistant


def test_export_sessions_with_empty_selection_exports_none(tmp_path, monkeypatch):
    from routes import sessions as sessions_routes

    store = SessionStore(db_path=str(tmp_path / "sessions.db"))
    store.append_message("s1", "default", "user", "hello")
    monkeypatch.setattr(
        sessions_routes,
        "get_session_store",
        lambda project_id="default": store,
    )

    with _client() as client:
        response = client.get(
            "/brain/sessions/export",
            params={"session_ids": ""},
        )

    assert response.status_code == 200
    assert response.json()["sessions"] == []
    assert response.json()["total_sessions"] == 0


def test_simple_export_keeps_only_role_content_time(tmp_path, monkeypatch):
    from routes import sessions as sessions_routes

    store = SessionStore(db_path=str(tmp_path / "sessions.db"))
    store.append_message("s1", "default", "user", "問題")
    store.append_message(
        "s1", "default", "assistant", "回答",
        metadata={"response_time_s": 1.5, "tool_steps": [{"name": "search_knowledge"}]},
    )
    monkeypatch.setattr(sessions_routes, "get_session_store", lambda project_id="default": store)

    with _client() as client:
        response = client.get("/brain/sessions/export", params={"simple": "true"})

    assert response.status_code == 200
    messages = response.json()["sessions"][0]["messages"]
    assert [set(m) for m in messages] == [{"role", "content", "created_at"}] * 2
    assert [m["content"] for m in messages] == ["問題", "回答"]


def test_batch_delete_reports_deleted_and_missing(monkeypatch):
    from routes import sessions as sessions_routes

    existing = {"a", "b"}
    calls = []

    def fake_delete(project_id="default", session_id=""):
        calls.append((project_id, session_id))
        return session_id in existing

    monkeypatch.setattr(sessions_routes, "delete_session_for_project", fake_delete)

    with _client() as client:
        response = client.post(
            "/brain/sessions/batch-delete",
            params={"project_id": "p1"},
            json={"session_ids": ["a", "ghost", "b", "a", " "]},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "deleted": ["a", "b"], "missing": ["ghost"]}
    assert calls == [("p1", "a"), ("p1", "ghost"), ("p1", "b")]   # 去重、略過空白


def test_batch_delete_rejects_empty_list():
    with _client() as client:
        response = client.post("/brain/sessions/batch-delete", json={"session_ids": []})
    assert response.status_code == 422

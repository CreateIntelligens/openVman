from __future__ import annotations

from fastapi import FastAPI
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from internal_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_internal_enrich_accepts_forward_payload_and_stores_system_message():
    with (
        patch("internal_routes.get_or_create_session", return_value=SimpleNamespace(session_id="sess-1")),
        patch("internal_routes.append_session_message") as append_session_message,
        patch("internal_routes.log_event"),
    ):
        with _client() as client:
            response = client.post(
                "/internal/enrich",
                json={
                    "trace_id": "trace-1",
                    "session_id": "sess-1",
                    "enriched_context": [{"type": "image_description", "content": "有一張胸腔 X 光"}],
                    "media_refs": [{"path": "/tmp/xray.jpg"}],
                },
            )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "trace_id": "trace-1",
        "session_id": "sess-1",
        "stored_count": 1,
    }
    append_session_message.assert_called_once()
    call = append_session_message.call_args
    assert call.args[:3] == ("sess-1", "default", "system")
    assert "image_description" in call.args[3]
    assert "胸腔 X 光" in call.args[3]
    assert "/tmp/xray.jpg" in call.args[3]


def test_internal_enrich_accepts_gateway_spec_payload_shape():
    with (
        patch("internal_routes.get_or_create_session", return_value=SimpleNamespace(session_id="sess-2")),
        patch("internal_routes.append_session_message") as append_session_message,
        patch("internal_routes.log_event"),
    ):
        with _client() as client:
            response = client.post(
                "/internal/enrich",
                json={
                    "trace_id": "trace-2",
                    "session_id": "sess-2",
                    "enriched_context": [
                        {"type": "crawl_result", "content": "最新門診公告"},
                        {"type": "tool_result", "content": "掛號 API 回傳成功"},
                    ],
                    "project_id": "default",
                    "persona_id": "doctor01",
                },
            )

    assert response.status_code == 200
    assert response.json()["stored_count"] == 2
    assert append_session_message.call_count == 2


def test_internal_enrich_rejects_empty_context_payload():
    with (
        patch("internal_routes.get_or_create_session", return_value=SimpleNamespace(session_id="sess-3")),
        patch("internal_routes.append_session_message") as append_session_message,
        patch("internal_routes.log_event"),
    ):
        with _client() as client:
            response = client.post(
                "/internal/enrich",
                json={
                    "trace_id": "trace-3",
                    "session_id": "sess-3",
                    "enriched_context": [],
                },
            )

    assert response.status_code == 400
    assert response.json()["detail"] == "enriched_context 不可為空"
    append_session_message.assert_not_called()

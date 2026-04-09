from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


def test_build_health_payload_reports_dependency_checks_and_session_runtime():
    from health_payload import build_health_payload

    with (
        patch("health_payload.get_settings") as get_settings,
        patch("health_payload.get_db") as get_db,
        patch("health_payload.list_workspace_documents", return_value=["a.md", "b.md"]),
        patch("health_payload.list_personas", return_value=[{"persona_id": "default"}]),
        patch("health_payload.list_sessions_for_project", return_value=[{"session_id": "sess-1"}]),
        patch("health_payload.get_metrics_store") as get_metrics_store,
    ):
        get_settings.return_value = SimpleNamespace(
            llm_provider="gemini",
            llm_model="gemini-2.0-flash",
            resolve_embedding_backend=lambda: SimpleNamespace(
                version="bge",
                provider="bge",
                model="BAAI/bge-m3",
            ),
        )
        get_db.return_value = SimpleNamespace(table_names=lambda: ["knowledge", "memories"])
        get_metrics_store.return_value.snapshot.return_value = {
            "counters": {"http_requests_total": 3},
            "timings": {"http_request_duration_ms": [1.2]},
        }

        payload = build_health_payload("default")

    assert payload["status"] == "ok"
    assert payload["active_sessions"] == 0
    assert payload["realtime_sessions_enabled"] is False
    assert payload["stored_sessions"] == 1
    assert payload["dependency_checks"]["db"]["status"] == "ok"
    assert payload["dependency_checks"]["workspace"]["status"] == "ok"
    assert payload["dependency_checks"]["embedding"]["status"] == "ok"
    assert payload["dependency_checks"]["session_runtime"] == {
        "status": "disabled",
        "transport": "http_sse",
        "active_sessions": 0,
    }


def test_build_health_payload_degrades_when_dependency_probe_fails():
    from health_payload import build_health_payload

    with (
        patch("health_payload.get_settings") as get_settings,
        patch("health_payload.get_db", side_effect=RuntimeError("db down")),
        patch("health_payload.list_workspace_documents", side_effect=RuntimeError("workspace down")),
        patch("health_payload.list_personas", return_value=[]),
        patch("health_payload.list_sessions_for_project", return_value=[]),
        patch("health_payload.get_metrics_store") as get_metrics_store,
    ):
        get_settings.return_value = SimpleNamespace(
            llm_provider="gemini",
            llm_model="gemini-2.0-flash",
            resolve_embedding_backend=lambda: SimpleNamespace(
                version="bge",
                provider="bge",
                model="BAAI/bge-m3",
            ),
        )
        get_metrics_store.return_value.snapshot.return_value = {
            "counters": {},
            "timings": {},
        }

        payload = build_health_payload("default")

    assert payload["status"] == "degraded"
    assert payload["tables"] == []
    assert payload["workspace_documents"] == 0
    assert payload["dependency_checks"]["db"]["status"] == "error"
    assert payload["dependency_checks"]["workspace"]["status"] == "error"

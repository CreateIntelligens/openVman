"""Helpers for building the brain health payload."""

from __future__ import annotations

from typing import Any, Callable


def get_settings():
    from config import get_settings as _get_settings

    return _get_settings()


def get_db(project_id: str = "default"):
    from infra.db import get_db as _get_db

    return _get_db(project_id)


def list_workspace_documents(project_id: str = "default"):
    from knowledge.knowledge_admin import list_workspace_documents as _list_workspace_documents

    return _list_workspace_documents(project_id)


def build_readiness_payload() -> dict[str, object]:
    """Lightweight readiness check — single DB connection ping, no table scans."""
    try:
        get_db().table_names()  # cheapest possible lancedb probe
        return {"status": "ready", "db": "ok"}
    except Exception as exc:
        return {"status": "not_ready", "db": "error", "db_error": str(exc)}


def list_personas(project_id: str = "default"):
    from personas.personas import list_personas as _list_personas

    return _list_personas(project_id)


def list_sessions_for_project(project_id: str = "default"):
    from memory.memory import list_sessions_for_project as _list_sessions_for_project

    return _list_sessions_for_project(project_id=project_id)


def get_metrics_store():
    from safety.observability import get_metrics_store as _get_metrics_store

    return _get_metrics_store()


def _probe(name: str, fn: Callable[[], Any], fallback: Any) -> dict[str, Any]:
    try:
        return {
            "name": name,
            "status": "ok",
            "value": fn(),
        }
    except Exception as exc:
        return {
            "name": name,
            "status": "error",
            "value": fallback,
            "error": str(exc),
        }


def build_health_payload(project_id: str = "default") -> dict[str, object]:
    """Assemble a dependency-aware health response for the brain service."""
    cfg = get_settings()
    metrics = get_metrics_store().snapshot()

    db_probe = _probe("db", lambda: list(get_db(project_id).table_names()), [])
    workspace_probe = _probe("workspace", lambda: list(list_workspace_documents(project_id)), [])
    persona_probe = _probe("personas", lambda: list(list_personas(project_id)), [])
    session_probe = _probe("session_store", lambda: list(list_sessions_for_project(project_id)), [])
    embedding_probe = _probe("embedding", cfg.resolve_embedding_backend, None)

    degraded = any(
        probe["status"] == "error"
        for probe in (db_probe, workspace_probe, persona_probe, session_probe, embedding_probe)
    )
    embedding_backend = embedding_probe["value"]
    dependency_checks: dict[str, Any] = {
        "db": {
            "status": db_probe["status"],
            "tables": db_probe["value"],
        },
        "workspace": {
            "status": workspace_probe["status"],
            "document_count": len(workspace_probe["value"]),
        },
        "personas": {
            "status": persona_probe["status"],
            "count": len(persona_probe["value"]),
        },
        "session_store": {
            "status": session_probe["status"],
            "stored_sessions": len(session_probe["value"]),
        },
        "embedding": {
            "status": embedding_probe["status"],
            "version": getattr(embedding_backend, "version", ""),
            "provider": getattr(embedding_backend, "provider", ""),
            "model": getattr(embedding_backend, "model", ""),
        },
        "session_runtime": {
            "status": "disabled",
            "transport": "http_sse",
            "active_sessions": 0,
        },
    }
    for key, probe in (
        ("db", db_probe),
        ("workspace", workspace_probe),
        ("personas", persona_probe),
        ("session_store", session_probe),
        ("embedding", embedding_probe),
    ):
        if probe["status"] == "error":
            dependency_checks[key]["error"] = probe["error"]

    return {
        "status": "degraded" if degraded else "ok",
        "project_id": project_id,
        "tables": db_probe["value"],
        "workspace_documents": len(workspace_probe["value"]),
        "personas": len(persona_probe["value"]),
        "stored_sessions": len(session_probe["value"]),
        "active_sessions": 0,
        "realtime_sessions_enabled": False,
        "chat_enabled": True,
        "embedding_version": getattr(embedding_backend, "version", ""),
        "embedding_model": getattr(embedding_backend, "model", ""),
        "llm_provider": cfg.llm_provider,
        "llm_model": cfg.llm_model,
        "metrics_summary": {
            "counter_count": len(metrics["counters"]),
            "timing_count": len(metrics["timings"]),
        },
        "dependency_checks": dependency_checks,
    }

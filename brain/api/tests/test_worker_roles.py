"""Protect the admin/chat role boundary and admin-owned background work."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI


def _flatten_routes(routes, prefix=""):
    # FastAPI 0.162+ keeps included routers as lazy wrappers in app.routes;
    # older versions copy each route in. Walk both shapes.
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from _flatten_routes(
                included.routes, prefix + route.include_context.prefix,
            )
        else:
            yield prefix + route.path, route


def _route_set(app):
    return {
        (path, method)
        for path, route in _flatten_routes(app.routes)
        for method in (getattr(route, "methods", None) or {"WS"})
    }


def test_chat_exposes_only_conversation_and_system_routes():
    from main import create_app

    chat, admin = _route_set(create_app("chat")), _route_set(create_app("admin"))
    expected = {
        ("/internal/decision", "POST"), ("/internal/enrich", "POST"),
        ("/brain/internal/live/{relay_session_id}", "WS"),
        ("/brain/internal/asr-glossary", "GET"),
        ("/brain/internal/asr-judge", "POST"),
        ("/brain/internal/audio-language", "POST"),
        ("/brain/chat", "POST"), ("/brain/chat/stream", "POST"),
        ("/brain/chat/accept", "POST"), ("/brain/chat/modes", "GET"),
        ("/brain/chat/history", "GET"), ("/brain/search", "POST"),
        ("/brain/knowledge/settings", "GET"),
    }
    system = {
        (path, "GET") for path in (
            "/brain/health", "/brain/health/ready", "/brain/health/detailed",
            "/brain/metrics", "/brain/metrics/prometheus", "/brain/identity",
        )
    } | {
        (path, method)
        for path in (
            "/brain/openapi.json", "/brain/docs",
            "/brain/docs/oauth2-redirect", "/brain/redoc",
        )
        for method in ("GET", "HEAD")
    }
    assert chat == expected | system
    assert chat <= admin
    assert ("/brain/skills/{skill_id}/toggle", "PATCH") in admin
    assert ("/brain/knowledge/settings", "PUT") in admin
    assert ("/brain/usage/events", "POST") in admin


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["chat", "admin"])
async def test_lifespan_only_starts_management_work_for_admin(monkeypatch, role):
    import memory.dreaming.scheduler as dreaming
    import memory.maintenance_scheduler as maintenance
    import memory.session_backup as backup
    import scripts.migrate_to_projects as migration
    import startup

    cfg = SimpleNamespace(
        brain_role=role, brain_workers=1, brain_thread_pool_size=0,
        brain_coordination_dir="", dreaming_enabled=True,
    )
    monkeypatch.setattr(startup, "get_settings", lambda: cfg)
    scaffold, database = Mock(), Mock()
    warmup, dream = AsyncMock(), AsyncMock()
    backups, maintain = Mock(return_value=None), Mock(return_value=None)
    monkeypatch.setattr(startup, "ensure_workspace_scaffold", scaffold)
    monkeypatch.setattr(startup, "get_db", database)
    monkeypatch.setattr(migration, "run_migration", Mock())
    monkeypatch.setattr(startup, "warmup_resources", warmup)
    monkeypatch.setattr(dreaming, "start_dreaming_scheduler", dream)
    monkeypatch.setattr(backup, "start_backup_scheduler", backups)
    monkeypatch.setattr(maintenance, "start_maintenance_scheduler", maintain)
    app = FastAPI()
    app.state.brain_role = role
    async with startup.lifespan(app):
        await asyncio.sleep(0)
        assert warmup.await_args.args == (role,)
    expected = 1 if role == "admin" else 0
    assert scaffold.call_count == database.call_count == expected
    assert migration.run_migration.call_count == expected
    assert dream.await_count == backups.call_count == maintain.call_count == expected


@pytest.mark.asyncio
async def test_chat_warmup_only_reads_retrieval_paths(monkeypatch):
    import startup

    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default", "new"])
    for name in ("_warmup_audio_language", "get_embedder", "mark_warmup_done"):
        monkeypatch.setattr(startup, name, Mock())
    ensure_tables, scaffold, maintenance, retrieval = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(startup, "ensure_tables", ensure_tables)
    monkeypatch.setattr(startup, "ensure_workspace_scaffold", scaffold)
    monkeypatch.setattr(startup, "maybe_run_memory_maintenance", maintenance)
    monkeypatch.setattr(startup, "_warmup_retrieval_path", retrieval)
    await startup.warmup_resources("chat")
    assert [call.args for call in retrieval.call_args_list] == [("default",), ("new",)]
    ensure_tables.assert_not_called()
    scaffold.assert_not_called()
    maintenance.assert_not_called()


def test_chat_never_runs_requested_or_forced_memory_maintenance(monkeypatch):
    import memory.memory_governance as governance

    monkeypatch.setattr(governance, "get_settings", lambda: SimpleNamespace(brain_role="chat"))
    work = Mock()
    monkeypatch.setattr(governance, "_run_memory_maintenance_locked", work)
    assert governance.request_memory_maintenance("new") is False
    assert governance.maybe_run_memory_maintenance(True, "new")["reason"] == "chat_role"
    assert governance.run_memory_maintenance("new")["reason"] == "chat_role"
    work.assert_not_called()


def test_admin_scheduler_detects_new_project_and_new_wal_messages(monkeypatch, tmp_path):
    import memory.maintenance_scheduler as scheduler
    from memory.session_store import SessionStore

    monkeypatch.setattr(scheduler, "get_settings", lambda: SimpleNamespace(brain_role="admin"))
    monkeypatch.setattr(scheduler, "get_data_root", lambda: tmp_path)
    work = Mock(return_value={"status": "ok"})
    monkeypatch.setattr(scheduler, "maybe_run_memory_maintenance", work)
    seen = {}
    scheduler.maintain_active_projects(seen)
    work.assert_not_called()
    store = SessionStore(tmp_path / "new-project" / "sessions.db")
    store.append_message("session", "default", "assistant", "first")
    scheduler.maintain_active_projects(seen)
    work.assert_called_once_with(True, "new-project")
    scheduler.maintain_active_projects(seen)
    assert work.call_count == 1
    store.append_message("session", "default", "assistant", "second")
    scheduler.maintain_active_projects(seen)
    assert work.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["run_id", "coordination_dir"])
async def test_multiworker_startup_requires_shared_configuration(monkeypatch, missing, tmp_path):
    import startup

    cfg = SimpleNamespace(
        brain_role="chat", brain_workers=4, brain_thread_pool_size=0,
        brain_coordination_dir=str(tmp_path) if missing != "coordination_dir" else "",
    )
    monkeypatch.setattr(startup, "get_settings", lambda: cfg)
    if missing == "run_id":
        monkeypatch.delenv("BRAIN_METRICS_RUN_ID", raising=False)
    else:
        monkeypatch.setenv("BRAIN_METRICS_RUN_ID", "testepoch")
    app = FastAPI()
    app.state.brain_role = "chat"
    with pytest.raises(RuntimeError, match="requires BRAIN_"):
        async with startup.lifespan(app):
            pytest.fail("invalid multi-worker configuration must fail startup")

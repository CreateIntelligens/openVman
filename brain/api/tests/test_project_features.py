"""Per-project feature settings at the startup, chat, Live and management boundaries."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from infra.project_context import resolve_project_context
from knowledge.kb_settings import load_kb_settings


def settings_path(project_id: str) -> Path:
    path = resolve_project_context(project_id).workspace_root / ".kb_settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_settings(project_id: str, **settings) -> Path:
    path = settings_path(project_id)
    path.write_text(json.dumps(settings), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _real_memory_module(monkeypatch):
    """其他測試會在 patch 過的環境裡重新 import memory.memory 並留在 sys.modules，
    那份模組綁著別的測試的工作區；這裡每次換一份乾淨的，測完放回原本那份。"""
    import importlib
    import sys

    monkeypatch.delitem(sys.modules, "memory.memory", raising=False)
    importlib.import_module("memory.memory")


@pytest.fixture
def startup_without_background_work(monkeypatch, tmp_path):
    from scripts import migrate_to_projects
    import startup

    monkeypatch.setattr(migrate_to_projects, "_DATA_ROOT", tmp_path / "flat")
    for step in ("_migrate_lancedb", "_migrate_sessions_db", "_migrate_index_state"):
        monkeypatch.setattr(migrate_to_projects, step, lambda: False)
    monkeypatch.setattr(startup, "warmup_resources", AsyncMock())
    monkeypatch.setattr(startup, "get_db", Mock())
    monkeypatch.setattr(startup, "shutdown_usage_writer", Mock(return_value=True))
    monkeypatch.setattr("infra.db.ensure_tables", Mock())
    monkeypatch.setattr("memory.maintenance_scheduler.start_maintenance_scheduler", Mock(return_value=None))
    monkeypatch.setattr("memory.session_backup.start_backup_scheduler", Mock(return_value=None))
    monkeypatch.setenv("DREAMING_ENABLED", "false")
    return startup


@pytest.mark.asyncio
async def test_admin_lifespan_accepts_readonly_legacy_workspace(startup_without_background_work):
    from infra.project_context import get_data_root

    legacy = write_settings("legacy", language_routes=["en"], reply_seconds=0)
    damaged = settings_path("damaged")
    damaged.write_text("{broken json", encoding="utf-8")
    legacy.parent.chmod(0o555)
    try:
        async with startup_without_background_work.lifespan(FastAPI()):
            assert load_kb_settings("legacy") == {
                "language_routes": ["en"], "reply_seconds": 0,
                "memory_enabled": True, "graph_enabled": True,
            }
            assert load_kb_settings("damaged")["memory_enabled"] is False
            assert damaged.read_text() == "{broken json"
            assert json.loads(legacy.read_text()) == {"language_routes": ["en"], "reply_seconds": 0}
            assert not list(get_data_root().glob(".memory-graph-settings-v1*"))
    finally:
        legacy.parent.chmod(0o755)


@pytest.mark.asyncio
async def test_fresh_default_and_created_projects_persist_disabled(
    startup_without_background_work, monkeypatch,
):
    from infra.project_admin import create_project

    monkeypatch.setenv("DEFAULT_PROJECT_ID", "custom-default")
    disabled = {"memory_enabled": False, "graph_enabled": False}
    async with startup_without_background_work.lifespan(FastAPI()):
        assert json.loads(settings_path("default").read_text()) == disabled
        assert load_kb_settings("custom-default")["memory_enabled"] is False
        project = create_project("New customer")["project_id"]
        assert json.loads(settings_path(project).read_text()) == disabled


@pytest.mark.asyncio
async def test_flat_default_migrates_before_scaffold(startup_without_background_work, tmp_path):
    from scripts import migrate_to_projects

    flat = migrate_to_projects._DATA_ROOT / "workspace"
    flat.mkdir(parents=True)
    (flat / ".kb_settings.json").write_text('{"language_routes": ["es"]}')
    (flat / "MEMORY.md").write_text("legacy memory")
    async with startup_without_background_work.lifespan(FastAPI()):
        assert not flat.exists()
        assert (resolve_project_context().workspace_root / "MEMORY.md").read_text() == "legacy memory"
        settings = load_kb_settings()
        assert settings["language_routes"] == ["es"]
        assert settings["memory_enabled"] is settings["graph_enabled"] is True


@pytest.mark.asyncio
async def test_restored_and_rollback_settings_keep_missing_features_enabled(startup_without_background_work):
    from infra.project_context import get_data_root

    # A prior release's marker must have no effect on a restored workspace.
    (get_data_root() / ".memory-graph-settings-v1").write_text("1\n")
    async with startup_without_background_work.lifespan(FastAPI()):
        path = write_settings("restored", graph_enabled=False)
        assert load_kb_settings("restored")["memory_enabled"] is True
        assert load_kb_settings("restored")["graph_enabled"] is False

    # Chat can deploy ahead of admin. Simulate an older writer dropping both switches.
    path.write_text('{"language_routes": ["en"]}')
    app = FastAPI()
    app.state.brain_role = "chat"
    async with startup_without_background_work.lifespan(app):
        current = load_kb_settings("restored")
        assert current["memory_enabled"] is current["graph_enabled"] is True
        assert json.loads(path.read_text()) == {"language_routes": ["en"]}


@pytest.mark.parametrize("existing", [None, {"graph_enabled": False, "custom": "keep"}])
def test_language_save_keeps_missing_feature_fields(existing):
    from knowledge.kb_settings import save_kb_settings, save_project_features

    if existing is not None:
        write_settings("legacy", **existing)
    current = save_kb_settings("legacy", language_routes=["en"])
    assert json.loads(settings_path("legacy").read_text()) == {
        **(existing or {}), "language_routes": ["en"],
    }
    assert current["memory_enabled"] is True
    assert current["graph_enabled"] is (existing is None)
    if existing is None:
        current = save_project_features("legacy", memory_enabled=False)
        assert current["graph_enabled"] is True
        assert "graph_enabled" not in json.loads(settings_path("legacy").read_text())


@pytest.mark.parametrize("raw", [
    b"", b"{broken json", b"\xff", b"[]", b"null",
    b'{"memory_enabled":"true","graph_enabled":1,"reply_seconds":NaN}',
])
def test_damaged_settings_and_nonboolean_values_default_to_disabled(raw):
    settings_path("p").write_bytes(raw)
    current = load_kb_settings("p")
    assert current["memory_enabled"] is False
    assert current["graph_enabled"] is False
    assert current["reply_seconds"] == 20


def test_nonboolean_feature_is_disabled_without_affecting_missing_peer():
    from knowledge.kb_settings import save_kb_settings

    path = write_settings("legacy", memory_enabled="true")
    result = save_kb_settings("legacy", language_routes=["en"])
    assert result["memory_enabled"] is False
    assert result["graph_enabled"] is True
    assert json.loads(path.read_text()) == {
        "memory_enabled": "true", "language_routes": ["en"],
    }


@pytest.mark.asyncio
async def test_brain_checks_feature_header_and_preserves_the_other_settings():
    from routes.knowledge import router

    write_settings("p", language_routes=["en"], reply_seconds=0, graph_enabled=True)
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Internal-Token": "test-internal-token"},
    ) as client:
        body = {"project_id": "p", "memory_enabled": True}
        for grant in ("", "edit_knowledge"):
            response = await client.patch(
                "/brain/knowledge/features", json=body,
                headers={"X-OpenVMan-Project-Writes": grant},
            )
            assert response.status_code == 403
        headers = {"X-OpenVMan-Project-Writes": "edit_settings"}
        for invalid in ({}, {"memory_enabled": None}, {"memory_enabled": "true"}):
            response = await client.patch(
                "/brain/knowledge/features", json={"project_id": "p", **invalid}, headers=headers,
            )
            assert response.status_code == 422
        response = await client.patch("/brain/knowledge/features", json=body, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["language_routes"] == ["en"]
        assert response.json()["reply_seconds"] == 0
        assert response.json()["graph_enabled"] is True
        response = await client.put("/brain/knowledge/settings", json={
            "project_id": "p", "language_routes": ["zh"],
            "memory_enabled": False, "graph_enabled": False,
        })
        assert response.status_code == 200
        response = await client.get("/brain/knowledge/settings", params={"project_id": "p"})
        assert response.json()["language_routes"] == ["zh"]
        assert response.json()["memory_enabled"] is True
        assert response.json()["graph_enabled"] is True


def test_auto_recall_only_runs_jev_and_llm_for_enabled_project(monkeypatch):
    from core.prompt_builder import build_chat_messages
    from memory import auto_recall

    write_settings("on", memory_enabled=True)
    write_settings("off", memory_enabled=False)
    retrieval = Mock(return_value=SimpleNamespace(memory_results=[{"text": "memory"}]))
    jev_filter = Mock(side_effect=RuntimeError("exercise LLM fallback"))
    summarizer = Mock(return_value="Recall fixture content")
    monkeypatch.setenv("AUTO_RECALL_ENABLED", "true")
    monkeypatch.setenv("AUTO_RECALL_USE_JEV_FILTER", "true")
    monkeypatch.setenv("AUTO_RECALL_USE_LLM_SUMMARIZER", "true")
    monkeypatch.setattr("core.retrieval_service.retrieve_context", retrieval)
    monkeypatch.setattr("core.jev_client.jev_available", lambda: True)
    monkeypatch.setattr(auto_recall, "_jev_filter", jev_filter)
    monkeypatch.setattr(auto_recall, "_llm_summarize", summarizer)

    for project_id in ("off", "on"):
        system = build_chat_messages(
            "remember my preference", {"project_id": project_id}, [],
        )[0]["content"]
        assert ("ACTIVE_RECALL_CONTEXT" in system) == (project_id == "on")
        assert ("Recall fixture content" in system) == (project_id == "on")
    assert auto_recall.run_auto_recall([], "another question", "default", "off").status == "disabled"
    for dependency in (retrieval, jev_filter, summarizer):
        dependency.assert_called_once()


def test_decision_batch_omits_memory_when_disabled(monkeypatch):
    from core import turn_decisions

    write_settings("on", memory_enabled=True)
    write_settings("off", memory_enabled=False)
    provider = Mock(return_value=turn_decisions.DecisionResult(
        answers={"needs_memory": {"noul": 0.99}}, provider="test", hop_id="test", model="test",
    ))
    monkeypatch.setattr(turn_decisions, "decide", provider)

    for project_id in ("off", "on"):
        decision = turn_decisions.run_turn_decision(
            user_text="remember me", history=[], project_id=project_id, project_language="zh",
            speech_language="", available_tools=("search_knowledge", "search_memory"),
            config=turn_decisions.TurnDecisionConfig(), turn_id=project_id,
        )
        evidence, questions = provider.call_args.args
        assert ("needs_memory" in questions) == (project_id == "on")
        assert ("search_memory" in evidence["available_read_tools"]) == (project_id == "on")
        assert "needs_knowledge" in questions
        assert decision.policy.needs_memory is (True if project_id == "on" else None)
        assert decision.policy.auto_recall is False
    assert provider.call_count == 2


def test_http_tools_are_filtered_independently_for_each_project(monkeypatch):
    from core import agent_loop
    from core.llm_client import LLMReply

    memory = {"search_memory", "save_memory"}
    graph = {"graph_query", "graph_explain", "graph_status", "graphify:run"}
    write_settings("memory-only", memory_enabled=True, graph_enabled=False)
    write_settings("graph-only", memory_enabled=False, graph_enabled=True)
    write_settings("both", memory_enabled=True, graph_enabled=True)
    offered = memory | graph | {"search_knowledge"}
    registry = Mock()
    registry.build_openai_tools.return_value = [
        {"function": {"name": name}} for name in sorted(offered)
    ]
    monkeypatch.setattr(agent_loop, "get_tool_registry", lambda: registry)
    llm = Mock(return_value=LLMReply(content="answered", model="test", tool_calls=[]))
    monkeypatch.setattr(agent_loop, "_stream_turn", llm)
    monkeypatch.setattr(agent_loop, "_generate_turn", llm)
    messages = [{"role": "user", "content": "question"}]
    for project_id, tools in (("memory-only", memory), ("graph-only", graph), ("both", memory | graph)):
        project_graph = f"proj:{project_id}:graphify:run"
        project_tool = f"proj:{project_id}:other:run"
        registry.build_openai_tools.return_value = [
            {"function": {"name": name}}
            for name in sorted(offered | {project_graph, project_tool})
        ]
        result = agent_loop.run_agent_loop(
            messages, project_id=project_id, forced_tool_name=project_graph,
        )
        assert result.reply == "answered"
        expected = tools | {"search_knowledge", project_tool}
        if tools & graph:
            expected.add(project_graph)
        assert {t["function"]["name"] for t in llm.call_args.kwargs["tools"]} == expected
        forced = llm.call_args.kwargs.get("forced_tool_name")
        assert forced == (project_graph if tools & graph else None)


@pytest.mark.asyncio
async def test_live_setup_and_executor_use_project_memory_switch(monkeypatch):
    from config import BrainSettings
    from live.gemini_live import GeminiLiveSession

    write_settings("on", memory_enabled=True)
    write_settings("off", memory_enabled=False)
    cfg = BrainSettings(live_gemini_tools_enabled=True)
    for project_id in ("off", "on"):
        session = GeminiLiveSession(
            project_id=project_id, client_id="client", relay_session_id="relay", config=cfg,
        )
        setup = session._build_setup_message()
        names = {t["name"] for t in setup["tools"][0]["functionDeclarations"]}
        assert {"search_memory", "save_memory"}.issubset(names) == (project_id == "on")
        assert {"search_knowledge", "get_chat_history"}.issubset(names)
        search = AsyncMock(return_value={"found": True})
        save = Mock(return_value={"saved": True})
        monkeypatch.setattr(session._tools, "search", search)
        monkeypatch.setattr(session._tools, "save_memory", save)
        for name, result in (("search_memory", {"found": True}), ("save_memory", {"saved": True})):
            response = await session._tools.execute({"name": name}, user_message="remember this")
            if project_id == "on":
                assert response["response"] == result
            else:
                assert "error" in response["response"]
        assert search.call_count == save.call_count == int(project_id == "on")


@pytest.mark.asyncio
async def test_open_live_session_refreshes_setup_at_next_idle_turn(monkeypatch):
    from config import BrainSettings
    from internal_routes import _build_live_session

    write_settings("p", memory_enabled=True)
    history = Mock(return_value="previous chat")
    memory = Mock(return_value="previous memory")
    monkeypatch.setattr("internal_routes._build_history_context", history)
    monkeypatch.setattr("internal_routes._build_memory_context", memory)
    transports = [
        SimpleNamespace(
            connect=AsyncMock(), close=AsyncMock(), send_json=AsyncMock(),
            recv_json=AsyncMock(return_value={"setupComplete": {}}),
        )
        for _ in range(2)
    ]
    session = _build_live_session(
        "relay", client_id="client", project_id="p",
        persona_id="default", session_id="persisted", event_sink=None,
    )
    session.config = BrainSettings(live_gemini_tools_enabled=True, turn_decisions_enabled=False)
    session._transport_factory = Mock(side_effect=transports)
    monkeypatch.setattr(session._turns, "decide_text_turn", AsyncMock(return_value=True))
    try:
        await session.send_text_turn("first question")
        write_settings("p", memory_enabled=False)
        assert await session.ensure_connected() is transports[0]
        session._response_in_progress = False
        await session.send_text_turn("next question")

        for transport, expected_memory in zip(transports, (True, False)):
            setup = transport.send_json.call_args_list[0].args[0]["setup"]
            prompt = setup["systemInstruction"]["parts"][0]["text"]
            tools = {tool["name"] for tool in setup["tools"][0]["functionDeclarations"]}
            assert "previous chat" in prompt
            assert ("previous memory" in prompt) == expected_memory
            assert ("search_memory" in tools) == expected_memory
        transports[0].close.assert_awaited_once()
        assert session.session_id == "persisted"
        memory.assert_called_once()
        history.assert_called_once_with("persisted", "default", "p")
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("relay_init", [True, False])
async def test_live_snapshots_history_before_saving_first_text(
    monkeypatch, enabled, relay_init,
):
    from config import BrainSettings
    from internal_routes import _dispatch_live_event
    from live.gemini_live import GeminiLiveSession
    from memory.memory import append_session_message, list_session_messages

    write_settings("relay-project", memory_enabled=enabled)
    monkeypatch.setattr("memory.session_store.refine_language_in_background", lambda *_: None)
    append_session_message("chat", "default", "assistant", "previous answer", project_id="relay-project")
    memory_threads = []

    def read_memory(*_args):
        memory_threads.append(get_ident())
        return "recalled detail"

    monkeypatch.setattr("internal_routes._build_memory_context", read_memory)
    transport = SimpleNamespace(
        connect=AsyncMock(), close=AsyncMock(), send_json=AsyncMock(),
        recv_json=AsyncMock(return_value={"setupComplete": {}}),
    )

    def init_session(**kwargs):
        session = GeminiLiveSession(
            **kwargs, config=BrainSettings(live_gemini_tools_enabled=True),
            transport_factory=lambda _: transport,
        )
        monkeypatch.setattr(session._turns, "decide_text_turn", AsyncMock(return_value=True))
        return session

    monkeypatch.setattr("live.gemini_live.GeminiLiveSession", init_session)
    state = {
        "live_session": None, "session_id": "chat",
        "args": {"client_id": "client", "persona_id": "default", "project_id": "relay-project"},
    }
    try:
        if relay_init:
            await _dispatch_live_event(state, "relay", None, {
                "event": "relay_init", "project_id": "relay-project", "chat_session_id": "chat",
            })
            assert len(memory_threads) == int(enabled)
            transport.connect.assert_not_awaited()
        await _dispatch_live_event(state, "relay", None, {
            "event": "user_speak", "text": "first new question",
        })
        setup = transport.send_json.await_args_list[0].args[0]["setup"]
        prompt = setup["systemInstruction"]["parts"][0]["text"]
        assert "previous answer" in prompt
        assert "first new question" not in prompt
        assert ("recalled detail" in prompt) is enabled
        assert len(memory_threads) == int(enabled)
        assert get_ident() not in memory_threads
        assert [m["content"] for m in list_session_messages(
            "chat", project_id="relay-project",
        )] == ["previous answer", "first new question"]
    finally:
        if state["live_session"] is not None:
            await state["live_session"].close()


@pytest.mark.asyncio
async def test_http_and_live_archive_only_when_enabled_with_sqlite_history_and_export(monkeypatch):
    from config import BrainSettings
    from core import chat_service
    from core.pipeline import RouteDecision
    from live.gemini_live import GeminiLiveSession
    from memory.memory import (
        append_session_message_with_id,
        archive_session_turn,
        list_conversation_messages,
        update_session_message_metadata,
    )
    from routes.sessions import export_sessions

    schedule = Mock()
    monkeypatch.setattr(chat_service, "append_session_message_with_id", append_session_message_with_id)
    monkeypatch.setattr(chat_service, "archive_session_turn", archive_session_turn)
    monkeypatch.setattr(chat_service, "update_session_message_metadata", update_session_message_metadata)
    monkeypatch.setattr(chat_service, "_schedule_memory_writes", schedule)
    monkeypatch.setattr(chat_service, "_scan_user_pii", lambda *_: None)
    monkeypatch.setattr("memory.session_store.refine_language_in_background", lambda *_: None)
    for project_id in ("off", "on"):
        path = write_settings(project_id, memory_enabled=project_id == "on")
        ctx = chat_service.GenerationContext(
            trace_id="trace", session_id="http", project_id=project_id, persona_id="default",
            route=RouteDecision("direct", True, True), user_message="hello",
            request_context={}, prompt_messages=[],
        )
        chat_service.finalize_generation(ctx, "hi", [])
        session = GeminiLiveSession(
            project_id=project_id, client_id="client", relay_session_id="live", config=BrainSettings(),
        )
        await session._transcripts.save_user_speech("voice")
        session._transcripts.add_reply_text("voice answer")
        await session._transcripts.save_assistant_reply()
        await session._transcripts.archive_turn("voice", "voice answer")
        assert [m["content"] for m in list_conversation_messages("http", project_id=project_id)] == ["hello", "hi"]
        assert any(m["content"] == "voice answer" for m in list_conversation_messages("live", project_id=project_id))
        assert export_sessions(project_id=project_id)["total_messages"] >= 3
        daily = list((path.parent / "memory").glob("*/*.md"))
        assert bool(daily) == (project_id == "on")
        if daily:
            assert "voice answer" in daily[0].read_text()
            assert "hello" in daily[0].read_text()
    schedule.assert_called_once()


def test_sqlite_history_isolated_when_data_root_changes(monkeypatch, tmp_path):
    from memory.memory import append_session_message, list_conversation_messages

    monkeypatch.setattr("memory.session_store.refine_language_in_background", lambda *_: None)
    for index in range(2):
        monkeypatch.setattr("infra.project_context._DATA_ROOT", tmp_path / f"root-{index}")
        assert list_conversation_messages("http", project_id="same-project") == []
        for role, content in (("user", "hello"), ("assistant", "hi")):
            append_session_message("http", "default", role, content, project_id="same-project")
        history = list_conversation_messages("http", project_id="same-project")
        assert [m["content"] for m in history] == ["hello", "hi"]


@pytest.mark.asyncio
@pytest.mark.parametrize("via_http", [False, True])
async def test_dreaming_skips_disabled_memory_even_when_forced(monkeypatch, via_http):
    from internal_routes import router
    from memory.dreaming import scheduler

    path = write_settings("off", memory_enabled=False)
    rotates = Mock(return_value=0)
    monkeypatch.setattr(scheduler, "rotate_traces", rotates)
    for phase in ("light", "deep", "rem"):
        monkeypatch.setattr(
            f"memory.dreaming.{phase}_phase.run_{phase}_phase", Mock(return_value={}),
        )
    if via_http:
        app = FastAPI()
        app.include_router(router)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
            headers={"X-Internal-Token": "test-internal-token"},
        ) as client:
            response = await client.post("/brain/dreaming/run?project_id=off&force=true")
        assert response.status_code == 200
        result = response.json()
    else:
        result = scheduler.run_dreaming_cycle("off", force=True)

    assert result == {"status": "skipped", "reason": "memory_disabled", "project_id": "off"}
    rotates.assert_not_called()
    assert set(path.parent.iterdir()) == {path}


@pytest.mark.asyncio
async def test_dreaming_schedule_only_dispatches_projects_with_memory(monkeypatch):
    from memory.dreaming import scheduler

    monkeypatch.setenv("DREAMING_ENABLED", "true")
    monkeypatch.setenv("DREAMING_CRON", "* * * * *")
    write_settings("on", memory_enabled=True)
    write_settings("off", memory_enabled=False)
    monkeypatch.setattr(scheduler, "asyncio", SimpleNamespace(
        sleep=AsyncMock(side_effect=[None, asyncio.CancelledError()]),
        to_thread=asyncio.to_thread, create_task=asyncio.create_task,
    ))
    cycle = Mock()
    monkeypatch.setattr(scheduler, "run_dreaming_cycle", cycle)
    app = FastAPI()
    await scheduler.start_dreaming_scheduler(app)
    with pytest.raises(asyncio.CancelledError):
        await app.state.dreaming_task
    cycle.assert_called_once_with("on")


def test_get_document_respects_memory_setting():
    from knowledge.workspace import ensure_workspace_scaffold
    from tools.builtin.knowledge_tools import _get_document
    from tools.tool_registry import bind_tool_context

    private_paths = (
        "MEMORY.md", "MEMORY_SUMMARIES.md", "memory/default/2026-11-19.md",
        "archive/memory/default/2026-10-19.md",
    )
    for enabled in (True, False):
        project = f"memory-{enabled}"
        write_settings(project, memory_enabled=enabled)
        workspace = ensure_workspace_scaffold(project)
        for relative in (*private_paths, "knowledge/faq.md"):
            path = workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("document contents")
        (workspace / "knowledge" / "alias.md").symlink_to(workspace / "MEMORY.md")

        with bind_tool_context("default", project_id=project):
            assert _get_document({"path": "knowledge/faq.md"})["content"] == "document contents"
            for relative in (*private_paths, "knowledge/alias.md"):
                if enabled:
                    assert _get_document({"path": relative})["content"] == "document contents"
                else:
                    with pytest.raises(ValueError, match="專案記憶已關閉"):
                        _get_document({"path": relative})


def test_new_tools_template_works_without_memory_tools():
    from knowledge.workspace import ensure_workspace_scaffold

    write_settings("new", memory_enabled=False, graph_enabled=False)
    tools_doc = (ensure_workspace_scaffold("new") / "TOOLS.md").read_text()
    assert "search_knowledge" in tools_doc
    assert "get_document" in tools_doc
    assert "search_memory" not in tools_doc


def test_daily_summary_and_maintenance_skip_disabled_projects(monkeypatch):
    from memory import memory_governance as governance

    maintenance = Mock(return_value={"status": "ok"})
    monkeypatch.setattr(governance, "_run_memory_maintenance_locked", maintenance)
    for project_id in ("off", "on"):
        path = write_settings(project_id, memory_enabled=project_id == "on")
        result = governance.write_summary_and_reindex(
            persona_id="default", day="2026-11-19", summary_text="summary", project_id=project_id,
        )
        assert result["status"] == ("ok" if project_id == "on" else "skipped")
        assert bool(list((path.parent / "memory").glob("*/*.md"))) == (project_id == "on")
        timed = governance.maybe_run_memory_maintenance(True, project_id)
        assert timed["status"] == ("ok" if project_id == "on" else "skipped")
    assert [call.args for call in maintenance.call_args_list] == [("on",), ("on",)]


@pytest.mark.asyncio
async def test_graph_expansion_gates_neighbors_and_citations_but_keeps_management(monkeypatch):
    from routes import knowledge_graph
    from tools.builtin import knowledge_tools
    from tools.tool_registry import bind_tool_context

    write_settings("on", graph_enabled=True)
    write_settings("off", graph_enabled=False)
    hit = {"chunk_id": "one", "path": "base.md", "title": "Base", "text": "base"}
    neighbor = {"chunk_id": "two", "path": "related.md", "title": "Related", "text": "related"}
    monkeypatch.setattr(knowledge_tools, "_search_one", lambda *_a, **_k: ([hit], "gemma", [1.0]))
    expand = Mock(return_value=[neighbor])
    monkeypatch.setattr(knowledge_tools, "_expand_via_graph", expand)
    for project_id in ("off", "on"):
        with bind_tool_context("default", project_id):
            results = knowledge_tools._search_tool("knowledge", {"queries": ["base"]})
        assert [entry["path"] for entry in results["results"]] == ["base.md"]
        assert [entry["path"] for entry in results["related"]] == (
            ["related.md"] if project_id == "on" else []
        )
        assert {cite["uri"] for cite in results["citations"]} == (
            {"base.md", "related.md"} if project_id == "on" else {"base.md"}
        )
    expand.assert_called_once()

    # 管理路由仍以專案與圖譜狀態回應。
    graph = Mock(return_value={"nodes": []})
    rebuild = Mock(return_value=True)
    monkeypatch.setattr(knowledge_graph, "load_project_graph", graph)
    monkeypatch.setattr(knowledge_graph, "schedule_graph_rebuild", rebuild)
    app = FastAPI()
    app.include_router(knowledge_graph.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"X-Internal-Token": "test-internal-token"},
    ) as client:
        response = await client.get("/brain/knowledge/graph", params={"project_id": "off"})
        assert response.status_code == 200, response.text
        response = await client.post("/brain/knowledge/graph/rebuild", json={"project_id": "off"})
        assert response.status_code == 202, response.text
    graph.assert_called_once_with("off")
    rebuild.assert_called_once_with("off")


@pytest.mark.parametrize("raw", [b"{broken json", b"[]"])
def test_saving_routes_over_damaged_settings_keeps_features_disabled(raw):
    # 損壞時讀成關閉；只存語言分流不能讓缺欄位被當成舊專案而打開。
    from knowledge.kb_settings import save_kb_settings

    settings_path("p").write_bytes(raw)
    result = save_kb_settings("p", language_routes=["en"])

    assert result["memory_enabled"] is False
    assert result["graph_enabled"] is False
    assert load_kb_settings("p")["memory_enabled"] is False


def test_graph_switch_also_hides_project_level_graphify_skill():
    from tools.context import is_graph_tool

    assert is_graph_tool("graphify:run")
    assert is_graph_tool("proj:proj-abc:graphify:run")
    assert not is_graph_tool("proj:proj-abc:other:run")
    assert not is_graph_tool("search_knowledge")

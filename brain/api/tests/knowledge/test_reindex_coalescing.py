"""Reindex 排程的 single-flight 與 debounce 行為。"""

from __future__ import annotations

import asyncio

from routes import knowledge as knowledge_routes


def _setup(monkeypatch, calls):
    monkeypatch.setattr(knowledge_routes, "_REINDEX_DEBOUNCE_SECONDS", 0.05)
    monkeypatch.setattr(
        knowledge_routes,
        "rebuild_knowledge_index",
        lambda project_id: calls.append(project_id) or {"status": "ok"},
    )
    monkeypatch.setattr(knowledge_routes, "schedule_graph_rebuild", lambda project_id: True)
    knowledge_routes._reindex_state.clear()


def test_burst_of_requests_coalesces_into_one_run(monkeypatch):
    calls: list[str] = []
    _setup(monkeypatch, calls)

    async def scenario():
        for _ in range(5):
            knowledge_routes.schedule_reindex("p1")
        await asyncio.sleep(0.5)

    asyncio.run(scenario())
    assert calls == ["p1"]


def test_request_during_run_triggers_followup_run(monkeypatch):
    calls: list[str] = []
    _setup(monkeypatch, calls)
    started = asyncio.Event()
    release = asyncio.Event()

    async def scenario():
        loop = asyncio.get_running_loop()

        def slow_rebuild(project_id):
            loop.call_soon_threadsafe(started.set)
            while not release.is_set():
                pass
            calls.append(project_id)
            return {"status": "ok"}

        monkeypatch.setattr(knowledge_routes, "rebuild_knowledge_index", slow_rebuild)
        knowledge_routes.schedule_reindex("p1")
        await started.wait()
        knowledge_routes.schedule_reindex("p1")
        release.set()
        await asyncio.sleep(0.5)

    asyncio.run(scenario())
    assert calls == ["p1", "p1"]


def test_projects_do_not_block_each_other(monkeypatch):
    calls: list[str] = []
    _setup(monkeypatch, calls)

    async def scenario():
        knowledge_routes.schedule_reindex("p1")
        knowledge_routes.schedule_reindex("p2")
        await asyncio.sleep(0.5)

    asyncio.run(scenario())
    assert sorted(calls) == ["p1", "p2"]


def test_auto_reindex_rebuilds_the_graph_only_where_it_is_switched_on(monkeypatch):
    # 關掉圖譜的專案存檔後不排背景重建；手動重建路由不受影響（見 test_project_features）。
    from knowledge import kb_settings

    calls: list[str] = []
    _setup(monkeypatch, calls)
    scheduled: list[str] = []
    monkeypatch.setattr(knowledge_routes, "schedule_graph_rebuild", lambda project_id: scheduled.append(project_id) or True)
    monkeypatch.setattr(kb_settings, "load_kb_settings", lambda project_id: {"graph_enabled": project_id == "on"})

    async def scenario():
        knowledge_routes.schedule_reindex("on")
        knowledge_routes.schedule_reindex("off")
        await asyncio.sleep(0.5)

    asyncio.run(scenario())
    assert sorted(calls) == ["off", "on"]
    assert scheduled == ["on"]

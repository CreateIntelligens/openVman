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
    monkeypatch.setattr(knowledge_routes, "_schedule_graph_rebuild", lambda project_id: True)
    knowledge_routes._reindex_state.clear()


def test_burst_of_requests_coalesces_into_one_run(monkeypatch):
    calls: list[str] = []
    _setup(monkeypatch, calls)

    async def scenario():
        for _ in range(5):
            knowledge_routes._schedule_reindex("p1")
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
        knowledge_routes._schedule_reindex("p1")
        await started.wait()
        knowledge_routes._schedule_reindex("p1")
        release.set()
        await asyncio.sleep(0.5)

    asyncio.run(scenario())
    assert calls == ["p1", "p1"]


def test_projects_do_not_block_each_other(monkeypatch):
    calls: list[str] = []
    _setup(monkeypatch, calls)

    async def scenario():
        knowledge_routes._schedule_reindex("p1")
        knowledge_routes._schedule_reindex("p2")
        await asyncio.sleep(0.5)

    asyncio.run(scenario())
    assert sorted(calls) == ["p1", "p2"]

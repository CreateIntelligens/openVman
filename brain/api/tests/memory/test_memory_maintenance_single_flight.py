"""同一專案的記憶維護同時只跑一份；跑的期間進來的請求合併成跑完再補一次，不排隊等鎖。"""

from __future__ import annotations

import threading

import pytest

import memory.memory_governance as gov


@pytest.fixture
def runs(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(gov, "run_memory_maintenance", lambda project_id: calls.append(project_id))
    monkeypatch.setattr(gov, "_project_locks", {})
    monkeypatch.setattr(gov, "_pending_maintenance", set())
    monkeypatch.setattr(gov, "_last_maintenance_at", {})
    return calls


def test_idle_request_runs_now(runs):
    assert gov.request_memory_maintenance("p") is True
    assert runs == ["p"]


def test_request_during_a_run_returns_at_once_and_is_run_afterwards(monkeypatch, runs):
    started, release = threading.Event(), threading.Event()

    def slow(project_id):
        runs.append(project_id)
        if len(runs) == 1:
            started.set()
            assert release.wait(5)

    monkeypatch.setattr(gov, "run_memory_maintenance", slow)
    owner = threading.Thread(target=gov.request_memory_maintenance, args=("p",))
    owner.start()
    assert started.wait(5)
    # 第二、三個請求不等鎖，直接回去；它們會合併成一次補跑。
    assert gov.request_memory_maintenance("p") is False
    assert gov.request_memory_maintenance("p") is False
    release.set()
    owner.join(5)
    assert runs == ["p", "p"]


def test_projects_do_not_wait_for_each_other(monkeypatch, runs):
    started, release = threading.Event(), threading.Event()

    def slow(project_id):
        runs.append(project_id)
        if project_id == "a":
            started.set()
            assert release.wait(5)

    monkeypatch.setattr(gov, "run_memory_maintenance", slow)
    owner = threading.Thread(target=gov.request_memory_maintenance, args=("a",))
    owner.start()
    assert started.wait(5)
    assert gov.request_memory_maintenance("b") is True
    release.set()
    owner.join(5)
    assert sorted(runs) == ["a", "b"]


def test_a_failed_run_releases_the_project(monkeypatch, runs):
    def boom(project_id):
        raise RuntimeError("lance down")

    monkeypatch.setattr(gov, "run_memory_maintenance", boom)
    with pytest.raises(RuntimeError):
        gov.request_memory_maintenance("p")
    monkeypatch.setattr(gov, "run_memory_maintenance", lambda project_id: runs.append(project_id))
    assert gov.request_memory_maintenance("p") is True


def test_forced_maintenance_still_runs_while_throttled(runs):
    gov.maybe_run_memory_maintenance(force=True, project_id="p")
    assert gov.maybe_run_memory_maintenance(project_id="p")["status"] == "skipped"
    gov.maybe_run_memory_maintenance(force=True, project_id="p")
    assert runs == ["p", "p"]

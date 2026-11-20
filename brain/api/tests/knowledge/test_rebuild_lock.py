"""Rebuilds of one project never overlap, whoever triggers them."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from knowledge import indexer  # noqa: E402


def test_rebuilds_of_the_same_project_run_one_at_a_time(monkeypatch):
    running = 0
    peak = 0
    guard = threading.Lock()

    def slow_rebuild(project_id):
        nonlocal running, peak
        with guard:
            running += 1
            peak = max(peak, running)
        time.sleep(0.2)
        with guard:
            running -= 1
        return {"project_id": project_id}

    monkeypatch.setattr(indexer, "_rebuild_knowledge_index", slow_rebuild)
    threads = [
        threading.Thread(target=indexer.rebuild_knowledge_index, args=("same",))
        for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak == 1


def test_rebuilds_of_different_projects_do_not_wait_for_each_other(monkeypatch):
    started = []
    release = threading.Event()

    def blocking_rebuild(project_id):
        started.append(project_id)
        release.wait(2)
        return {}

    monkeypatch.setattr(indexer, "_rebuild_knowledge_index", blocking_rebuild)
    first = threading.Thread(target=indexer.rebuild_knowledge_index, args=("a",))
    second = threading.Thread(target=indexer.rebuild_knowledge_index, args=("b",))
    first.start()
    second.start()
    deadline = time.time() + 1
    while len(started) < 2 and time.time() < deadline:
        time.sleep(0.01)
    release.set()
    first.join()
    second.join()

    assert sorted(started) == ["a", "b"]

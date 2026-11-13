"""Real process contention must keep one deployment-wide budget."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

from infra.shared_budgets import FileSlots, RequestBudget


def _spend(directory, barrier, result):
    barrier.wait(timeout=10)
    budget = RequestBudget(directory)
    result.put(sum(budget.admit("chat:project:caller:web", 17) == 0 for _ in range(20)))


def _hold_slot(directory, ready, finish):
    slot = FileSlots(directory, 1)
    assert slot.acquire(blocking=False)
    ready.set()
    finish.wait(timeout=20)
    # Deliberately leave the descriptor open: process exit must release it.


def test_request_budget_is_shared_between_processes(tmp_path: Path):
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(4)
    result = ctx.Queue()
    workers = [
        ctx.Process(target=_spend, args=(str(tmp_path), barrier, result))
        for _ in range(4)
    ]
    for worker in workers:
        worker.start()
    try:
        accepted = sum(result.get(timeout=15) for _ in workers)
        assert accepted == 17
        for worker in workers:
            worker.join(timeout=10)
            assert worker.exitcode == 0
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=5)


def test_request_budget_isolates_callers_and_expires(tmp_path: Path):
    first, second = RequestBudget(str(tmp_path)), RequestBudget(str(tmp_path))
    assert first.admit("caller-a", 1, now=100) == 0
    assert second.admit("caller-a", 1, now=110) == 50
    assert second.admit("caller-b", 1, now=110) == 0
    assert first.admit("caller-a", 1, now=161) == 0


def test_pii_slots_hold_across_processes_and_recover_after_exit(tmp_path: Path):
    ctx = multiprocessing.get_context("spawn")
    ready, finish = ctx.Event(), ctx.Event()
    worker = ctx.Process(target=_hold_slot, args=(str(tmp_path), ready, finish))
    worker.start()
    try:
        assert ready.wait(timeout=10)
        contenders = [FileSlots(str(tmp_path), 1) for _ in range(8)]
        assert all(not slot.acquire(blocking=False) for slot in contenders)
        worker.terminate()
        worker.join(timeout=10)
        assert worker.exitcode is not None
        assert contenders[0].acquire(blocking=False)
        assert not contenders[1].acquire(blocking=False)
        contenders[0].release()
        assert contenders[1].acquire(blocking=False)
        contenders[1].release()
    finally:
        if worker.is_alive():
            worker.terminate()
        worker.join(timeout=5)

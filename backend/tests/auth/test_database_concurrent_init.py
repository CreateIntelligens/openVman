"""Several Backend processes start against one fresh auth database."""

from __future__ import annotations

import multiprocessing
import sqlite3

from app.auth.database import AuthDatabase


def _init(path: str, results) -> None:
    try:
        AuthDatabase(path).initialize()
        results.put("ok")
    except Exception as exc:  # noqa: BLE001 - report to the parent
        results.put(f"{type(exc).__name__}: {exc}")


def test_four_processes_initialize_one_fresh_database(tmp_path):
    path = str(tmp_path / "accounts.db")
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    workers = [context.Process(target=_init, args=(path, results)) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(60)
    outcomes = [results.get(timeout=5) for _ in workers]
    assert outcomes == ["ok"] * 4
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

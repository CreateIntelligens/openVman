"""Exercise real SQLite, Markdown, and LanceDB mutations across processes."""

from __future__ import annotations

import multiprocessing
import sqlite3
from datetime import datetime
from pathlib import Path


def _session_writer(path: str, barrier, index: int):
    from memory.session_store import SessionStore

    barrier.wait(timeout=15)
    store = SessionStore(path)
    for number in range(50):
        store.append_message("shared-session", "default", "assistant", f"{index}:{number}")


def _configure_root(root: str):
    from infra import project_context

    project_context._DATA_ROOT = Path(root)


def _transcript_writer(root: str, barrier, index: int):
    _configure_root(root)
    from memory.memory import archive_session_turn

    barrier.wait(timeout=15)
    for number in range(50):
        archive_session_turn(f"{index}:{number}", f"question-{index}-{number}", "answer")


def _summary_writer(root: str, barrier):
    _configure_root(root)
    from knowledge.workspace import ensure_workspace_scaffold
    from memory.memory_governance import _append_summary_block

    daily = ensure_workspace_scaffold() / "memory" / "default" / f"{datetime.now().astimezone().date().isoformat()}.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    barrier.wait(timeout=15)
    for index in range(50):
        _append_summary_block(daily, f"summary-{index}")


def _table_maintenance(root: str, database: str, read_ready, overwrite_allowed):
    import lancedb
    from memory import memory_governance as governance

    _configure_root(root)
    db = lancedb.connect(database)

    def rewrite(project_id):
        records = db.open_table("memories").to_arrow().to_pylist()
        read_ready.set()
        assert overwrite_allowed.wait(timeout=20)
        db.create_table("memories", data=records, mode="overwrite")
        return {"status": "ok"}

    governance._run_memory_maintenance_locked = rewrite
    governance.run_memory_maintenance("default")


def _table_add(root: str, database: str, attempting, completed):
    import lancedb
    from memory import memory

    _configure_root(root)
    db = lancedb.connect(database)
    memory.get_memories_table = lambda project_id: db.open_table("memories")
    attempting.set()
    memory.add_memory("new-during-maintenance", [0.1, 0.2])
    completed.set()


def _join(workers):
    for worker in workers:
        worker.join(timeout=30)
        assert worker.exitcode == 0


def _cleanup(workers):
    for worker in workers:
        if worker.is_alive():
            worker.terminate()
        worker.join(timeout=5)


def test_four_processes_initialize_and_append_to_one_wal_database(tmp_path: Path):
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(4)
    path = tmp_path / "sessions.db"
    workers = [
        ctx.Process(target=_session_writer, args=(str(path), barrier, index))
        for index in range(4)
    ]
    for worker in workers:
        worker.start()
    try:
        _join(workers)
        with sqlite3.connect(path) as connection:
            assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
            messages = connection.execute("SELECT content FROM conversation_messages").fetchall()
            assert {row[0] for row in messages} == {
                f"{worker}:{number}" for worker in range(4) for number in range(50)
            }
    finally:
        _cleanup(workers)


def test_two_hundred_transcript_appends_survive_summary_rewrites(tmp_path: Path):
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(5)
    workers = [
        ctx.Process(target=_transcript_writer, args=(str(tmp_path), barrier, index))
        for index in range(4)
    ] + [ctx.Process(target=_summary_writer, args=(str(tmp_path), barrier))]
    for worker in workers:
        worker.start()
    try:
        _join(workers)
        daily = tmp_path / "default" / "workspace" / "memory" / "default" / f"{datetime.now().astimezone().date().isoformat()}.md"
        text = daily.read_text()
        assert text.count("### User\n") == 200
        for worker in range(4):
            for number in range(50):
                assert text.count(f"question-{worker}-{number}\n") == 1
        for number in range(50):
            assert text.count(f"summary-{number}\n") == 1
    finally:
        _cleanup(workers)


def test_real_lancedb_add_waits_for_maintenance_overwrite(tmp_path: Path):
    # Import outside pytest's conftest LanceDB stub in a fresh interpreter.
    import json
    import os
    import subprocess
    import sys

    script = '''
import json, lancedb, sys
from memory.memory import build_memory_record
root=sys.argv[1]
db=lancedb.connect(root)
db.create_table("memories", data=[build_memory_record("original", [0.1, 0.2])])
'''
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    database = str(tmp_path / "lance")
    subprocess.run([sys.executable, "-c", script, database], env=env, check=True, timeout=30)
    ctx = multiprocessing.get_context("spawn")
    read_ready, allowed, attempting, completed = (ctx.Event() for _ in range(4))
    maintenance = ctx.Process(
        target=_table_maintenance,
        args=(str(tmp_path), database, read_ready, allowed),
    )
    addition = ctx.Process(
        target=_table_add,
        args=(str(tmp_path), database, attempting, completed),
    )
    workers = [maintenance, addition]
    maintenance.start()
    try:
        assert read_ready.wait(timeout=15)
        addition.start()
        assert attempting.wait(timeout=15)
        assert not completed.wait(timeout=0.3)
        allowed.set()
        _join(workers)
        result = subprocess.run(
            [sys.executable, "-c", 'import json,lancedb,sys; print(json.dumps(lancedb.connect(sys.argv[1]).open_table("memories").to_arrow().to_pylist()))', database],
            env=env, check=True, capture_output=True, text=True, timeout=30,
        )
        assert {row["text"] for row in json.loads(result.stdout)} == {
            "original", "new-during-maintenance",
        }
    finally:
        _cleanup([worker for worker in workers if worker.pid is not None])


def _new_shared_session_writer(path: str, barrier, index: int):
    from memory.session_store import SessionStore

    store = SessionStore(path)
    for number in range(10):
        barrier.wait(timeout=15)
        store.append_message(f"race-{number}", "default", "assistant", f"{index}:{number}")


def test_existing_workers_can_create_the_same_new_session(tmp_path: Path):
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(4)
    path = tmp_path / "sessions.db"
    workers = [
        ctx.Process(target=_new_shared_session_writer, args=(str(path), barrier, index))
        for index in range(4)
    ]
    for worker in workers:
        worker.start()
    try:
        _join(workers)
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM conversation_messages").fetchone() == (40,)
    finally:
        _cleanup(workers)


def _persona_claim_writer(path: str, barrier, index: int, results):
    from memory.session_store import SessionStore

    store = SessionStore(path)
    persona = f"persona-{index}"
    for number in range(10):
        barrier.wait(timeout=15)
        try:
            store.append_message(f"persona-race-{number}", persona, "assistant", persona)
        except ValueError:
            results.put((number, persona, "rejected"))
        else:
            results.put((number, persona, "accepted"))


def test_competing_personas_cannot_change_the_session_owner(tmp_path: Path):
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(2), ctx.Queue()
    path = tmp_path / "sessions.db"
    workers = [
        ctx.Process(target=_persona_claim_writer, args=(str(path), barrier, index, results))
        for index in range(2)
    ]
    for worker in workers:
        worker.start()
    try:
        outcomes = [results.get(timeout=15) for _ in range(20)]
        _join(workers)
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM conversation_messages").fetchone() == (10,)
            for number in range(10):
                attempts = [(persona, status) for turn, persona, status in outcomes if turn == number]
                assert sorted(status for _, status in attempts) == ["accepted", "rejected"]
                winner = next(persona for persona, status in attempts if status == "accepted")
                session = f"persona-race-{number}"
                assert connection.execute(
                    "SELECT persona_id FROM sessions WHERE session_id=?", (session,),
                ).fetchone() == (winner,)
                assert connection.execute(
                    "SELECT content FROM conversation_messages WHERE session_id=?", (session,),
                ).fetchall() == [(winner,)]
    finally:
        _cleanup(workers)


def _usage_writer(path: str, barrier, index: int):
    from core.usage import LLMUsage

    from infra import usage_ledger

    usage_ledger.set_usage_db_path(Path(path))
    barrier.wait(timeout=15)
    for number in range(50):
        usage_ledger.record_usage_event(
            provider="fake", model=f"{index}:{number}", usage=LLMUsage(1, 2, 3),
        )


def test_usage_wal_initialization_and_old_schema_migrations_are_process_safe(tmp_path: Path):
    from infra import usage_ledger

    for old_schema in (False, True):
        path = tmp_path / f"usage-{old_schema}.db"
        if old_schema:
            with sqlite3.connect(path) as connection:
                connection.executescript(usage_ledger._SCHEMA)
                for column, _ in usage_ledger._ADDED_COLUMNS:
                    connection.execute(f"ALTER TABLE usage_events DROP COLUMN {column}")
        ctx = multiprocessing.get_context("spawn")
        barrier = ctx.Barrier(4)
        workers = [
            ctx.Process(target=_usage_writer, args=(str(path), barrier, index))
            for index in range(4)
        ]
        for worker in workers:
            worker.start()
        try:
            _join(workers)
            # record_usage_event swallows SQLite failures: process exit alone
            # would incorrectly count dropped ledger events as a passing test.
            with sqlite3.connect(path) as connection:
                assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
                rows = connection.execute("SELECT model, total_tokens FROM usage_events").fetchall()
                assert set(rows) == {
                    (f"{index}:{number}", 3)
                    for index in range(4) for number in range(50)
                }
                columns = {row[1] for row in connection.execute("PRAGMA table_info(usage_events)")}
                assert {column for column, _ in usage_ledger._ADDED_COLUMNS} <= columns
        finally:
            _cleanup(workers)

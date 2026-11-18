"""Background writer of the usage ledger: the reply path must never wait on SQLite."""

from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from core.usage import LLMUsage, usage_scope
from infra import usage_ledger


@pytest.fixture()
def ledger(tmp_path: Path):
    path = tmp_path / "usage.db"
    usage_ledger.set_usage_db_path(path)
    # 先建好 schema，鎖資料庫的測試才是在鎖「寫入」而不是建表。
    usage_ledger._connect().close()
    yield path
    usage_ledger.set_usage_db_path(None)


def _row_count(path: Path) -> int:
    # 直接開連線讀，不經過會先 flush 的 list_usage_events，才驗得到背景寫入本身。
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]


def _hold_write_lock(path: Path) -> sqlite3.Connection:
    blocker = sqlite3.connect(path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    return blocker


def _record(model: str = "m") -> dict | None:
    return usage_ledger.record_usage_event(
        provider="jev", model=model, usage=LLMUsage(1, 2, 3),
    )


def test_record_does_not_wait_while_another_process_holds_the_write_lock(ledger):
    """正式站一秒 100 題時每次決策等了約 10 秒：記用量不能等 SQLite 寫鎖。"""
    blocker = _hold_write_lock(ledger)
    try:
        started = time.perf_counter()
        event = _record()
        elapsed = time.perf_counter() - started
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()

    assert elapsed < 0.1
    assert event is not None and event["model"] == "m"
    assert usage_ledger.flush_usage_events(timeout=10)
    assert _row_count(ledger) == 1


def test_background_writer_commits_events_on_flush(ledger):
    with usage_scope(kind="chat", user_id="u1", trace_id="t1") as scope:
        for index in range(3):
            _record(f"m{index}")

    assert len(scope.collected) == 3
    assert usage_ledger.flush_usage_events(timeout=5)
    assert _row_count(ledger) == 3
    with sqlite3.connect(ledger) as connection:
        rows = connection.execute(
            "SELECT model, user_id, trace_id FROM usage_events ORDER BY id",
        ).fetchall()
    assert rows == [("m0", "u1", "t1"), ("m1", "u1", "t1"), ("m2", "u1", "t1")]


def test_writer_flushes_without_an_explicit_flush(ledger, monkeypatch):
    monkeypatch.setattr(usage_ledger, "_FLUSH_INTERVAL_S", 0.05)
    _record()
    deadline = time.monotonic() + 5
    while _row_count(ledger) == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert _row_count(ledger) == 1


def test_locked_database_keeps_the_batch_and_retries(ledger, monkeypatch):
    """寫鎖被別的 process 拿著時保留整批重試，鎖一放開就全部寫入，不丟紀錄。"""
    monkeypatch.setattr(usage_ledger, "_WRITER_BUSY_TIMEOUT_MS", 20)
    monkeypatch.setattr(usage_ledger, "_RETRY_BACKOFF_MAX_S", 0.05)
    blocker = _hold_write_lock(ledger)
    try:
        for index in range(5):
            assert _record(f"m{index}") is not None
        assert usage_ledger.flush_usage_events(timeout=0.5) is False
        assert _row_count(ledger) == 0
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()

    assert usage_ledger.flush_usage_events(timeout=5)
    assert _row_count(ledger) == 5


def test_queue_cap_drops_new_events_and_warns_once(ledger, monkeypatch, caplog):
    # 拉長批次間隔，讓事件停在佇列裡，才測得到上限。
    monkeypatch.setattr(usage_ledger, "_FLUSH_INTERVAL_S", 30.0)
    monkeypatch.setattr(usage_ledger, "_QUEUE_CAP", 3)
    caplog.set_level(logging.WARNING, logger="brain.usage")

    with usage_scope(kind="chat") as scope:
        results = [_record(f"m{index}") for index in range(5)]

    assert [result is not None for result in results] == [True, True, True, False, False]
    # 被丟掉的事件不進 scope 鏡像，回應裡的用量摘要才跟帳本一致。
    assert len(scope.collected) == 3
    full = [record for record in caplog.records if "queue full" in record.getMessage()]
    assert len(full) == 1
    assert usage_ledger.flush_usage_events(timeout=5)
    assert _row_count(ledger) == 3


def test_shutdown_flushes_pending_events_and_writer_restarts(ledger, monkeypatch):
    monkeypatch.setattr(usage_ledger, "_FLUSH_INTERVAL_S", 30.0)
    _record("before")
    _record("before")

    usage_ledger.shutdown_usage_writer(timeout=5)

    assert _row_count(ledger) == 2
    thread = usage_ledger._WRITER.thread
    assert thread is not None and not thread.is_alive()

    # 測試會反覆進出 lifespan，停掉之後再記用量要能自己重新啟動。
    _record("after")
    assert usage_ledger.flush_usage_events(timeout=5)
    assert _row_count(ledger) == 3


def test_reads_in_the_same_process_see_queued_events(ledger, monkeypatch):
    monkeypatch.setattr(usage_ledger, "_FLUSH_INTERVAL_S", 30.0)
    _record("queued")
    events = usage_ledger.list_usage_events()
    assert [event["model"] for event in events] == ["queued"]
    assert usage_ledger.count_usage_events_since(
        provider="jev", kind="background", since="2000-01-01",
    ) == 1


def test_wal_is_truncated_after_checkpoints(ledger, monkeypatch):
    """常駐連線不會在關閉時 checkpoint；WAL 要靠定期 checkpoint 與大小上限收回來。"""
    monkeypatch.setattr(usage_ledger, "_CHECKPOINT_INTERVAL_S", 0.0)
    monkeypatch.setattr(usage_ledger, "_JOURNAL_SIZE_LIMIT_BYTES", 64 * 1024)
    usage_ledger.set_usage_db_path(ledger)
    wal = ledger.with_name(ledger.name + "-wal")

    payload = {"blob": "x" * 4000}
    for _ in range(400):
        usage_ledger.record_usage_event(
            provider="jev", model="big", usage=LLMUsage(1, 1, 2), raw=payload,
        )
    assert usage_ledger.flush_usage_events(timeout=10)
    _record("small")
    assert usage_ledger.flush_usage_events(timeout=5)

    assert _row_count(ledger) == 401
    assert wal.stat().st_size <= 256 * 1024


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs os.fork")
def test_forked_child_gets_its_own_writer(tmp_path: Path):
    """fork 出來的子 process 沒有父 process 的寫入執行緒，要自己開一條。

    另開直譯器跑，避免在 pytest 這個多執行緒 process 裡 fork。
    """
    path = tmp_path / "usage.db"
    script = textwrap.dedent(
        f"""
        import os, sys
        from pathlib import Path
        sys.path.insert(0, {str(API_ROOT)!r})
        from core.usage import LLMUsage
        from infra import usage_ledger

        usage_ledger.set_usage_db_path(Path({str(path)!r}))
        usage_ledger.record_usage_event(provider="p", model="parent", usage=LLMUsage(1, 1, 2))
        parent_writer = usage_ledger._WRITER
        pid = os.fork()
        if pid == 0:
            ok = usage_ledger._WRITER is not parent_writer
            usage_ledger.record_usage_event(provider="p", model="child", usage=LLMUsage(1, 1, 2))
            ok = ok and usage_ledger.flush_usage_events(timeout=10)
            os._exit(0 if ok else 1)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        assert usage_ledger.flush_usage_events(timeout=10)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as connection:
        models = {row[0] for row in connection.execute("SELECT model FROM usage_events")}
    assert models == {"parent", "child"}

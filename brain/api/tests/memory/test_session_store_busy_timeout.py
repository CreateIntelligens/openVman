"""A burst of turns finishing together must queue for the sessions.db write lock, not fail.

2026-11-17：16 個 worker 同時寫，5 秒等待時排在後面的寫入會被餓到 database is locked，
整輪對話丟掉。寫入都很短，等待上限要夠長。
"""
from memory.session_store import SessionStore


def test_session_connections_wait_long_enough_for_a_write_burst(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.db"))

    conn = store._connect()
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 30000
    finally:
        conn.close()

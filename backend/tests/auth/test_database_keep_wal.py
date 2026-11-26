"""The auth database keeps its WAL between requests.

When the last connection to a WAL database closes, SQLite checkpoints under an
exclusive lock on the whole file and fsyncs. On the production virtual disk that
fsync sometimes takes over a second, and every worker reading auth on its event
loop waited behind it (11/24 and 11/26: all workers stalled 1-2 s at once).
"""

import sqlite3

from app.auth.database import AuthDatabase


def _wal(db: AuthDatabase):
    return db.path.with_name(db.path.name + "-wal")


def test_closing_a_transaction_does_not_tear_down_the_wal(tmp_path):
    db = AuthDatabase(tmp_path / "auth.db")
    db.initialize()
    with db.transaction(write=True) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS probe (value TEXT)")
        connection.execute("INSERT INTO probe VALUES ('x')")

    # 交易用的連線關掉後 WAL 還在：沒有觸發最後一條連線關閉時的 checkpoint。
    assert _wal(db).exists()
    check = sqlite3.connect(db.path)
    assert check.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    check.close()


def test_the_kept_connection_does_not_block_other_writers(tmp_path):
    db = AuthDatabase(tmp_path / "auth.db")
    db.initialize()
    with db.transaction(write=True) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS probe (value TEXT)")

    other = AuthDatabase(db.path)
    with other.transaction(write=True) as connection:
        connection.execute("INSERT INTO probe VALUES ('from another process')")
    with db.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM probe").fetchone()[0] == 1


def test_a_new_database_still_switches_to_wal(tmp_path):
    db = AuthDatabase(tmp_path / "fresh.db")
    db.initialize()
    check = sqlite3.connect(db.path)
    assert check.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    check.close()


def test_close_writes_the_wal_back_so_a_restored_file_is_not_overwritten(tmp_path):
    db = AuthDatabase(tmp_path / "auth.db")
    db.initialize()
    with db.transaction(write=True) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS probe (value TEXT)")
        connection.execute("INSERT INTO probe VALUES ('kept')")

    db.close()

    # 停服務後 WAL 已寫回主檔：只看主檔（不帶 -wal）也讀得到剛寫的資料。
    assert not _wal(db).exists() or _wal(db).stat().st_size == 0
    copy = tmp_path / "copy.db"
    copy.write_bytes(db.path.read_bytes())
    check = sqlite3.connect(copy)
    assert check.execute("SELECT value FROM probe").fetchall() == [("kept",)]
    check.close()
    db.close()  # 重複呼叫無害

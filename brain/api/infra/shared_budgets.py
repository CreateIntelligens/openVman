"""Single-host request and PII budgets shared by admin and chat workers."""

from __future__ import annotations

import fcntl
import hashlib
import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from threading import Lock, local
from time import sleep, time

from infra.file_lock import file_lock


class RequestBudget:
    def __init__(self, directory: str) -> None:
        root = Path(directory)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._lock = Lock()
        with file_lock(root / "request-budget.db"):
            self._connection = sqlite3.connect(
                root / "request-budget.db", timeout=5, check_same_thread=False,
                isolation_level=None,
            )
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS requests (caller TEXT, stamp REAL)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS requests_caller ON requests(caller, stamp)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS requests_stamp ON requests(stamp)"
            )

    def admit(self, key: str, limit: int, *, now: float | None = None) -> float:
        """Return seconds until retry, or zero after atomically consuming one slot."""
        timestamp = time() if now is None else now
        # The ledger needs identity equality, not a second copy of account/IP data.
        caller = hashlib.sha256(key.encode()).hexdigest()
        with self._lock:
            connection = self._connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "DELETE FROM requests WHERE stamp < ?", (timestamp - 60,),
                )
                count, oldest = connection.execute(
                    "SELECT COUNT(*), MIN(stamp) FROM requests WHERE caller=?",
                    (caller,),
                ).fetchone()
                retry = max(0.001, oldest + 60 - timestamp) if count >= limit else 0
                if not retry:
                    connection.execute(
                        "INSERT INTO requests VALUES (?, ?)", (caller, timestamp),
                    )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        return retry


@lru_cache(maxsize=8)
def _request_budget(directory: str, process_id: int) -> RequestBudget:
    # A fork must not reuse its parent's SQLite connection or thread lock.
    return RequestBudget(directory)


def shared_request_budget(directory: str) -> RequestBudget:
    return _request_budget(str(Path(directory).resolve()), os.getpid())


class FileSlots:
    """Nonblocking leases released by the kernel when a worker exits."""

    def __init__(self, directory: str, size: int) -> None:
        self._root = Path(directory) / "pii-slots"
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._size = size
        self._held = local()

    def acquire(self, blocking: bool = True) -> bool:
        while True:
            for index in range(self._size):
                descriptor = os.open(
                    self._root / str(index), os.O_CREAT | os.O_RDWR | os.O_CLOEXEC,
                    0o600,
                )
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(descriptor)
                    continue
                except BaseException:
                    os.close(descriptor)
                    raise
                if not hasattr(self._held, "descriptors"):
                    self._held.descriptors = []
                self._held.descriptors.append(descriptor)
                return True
            if not blocking:
                return False
            sleep(0.01)

    def release(self) -> None:
        if not getattr(self._held, "descriptors", None):
            raise ValueError("PII slot released without acquisition")
        # Closing the descriptor releases flock, including after abnormal exits.
        os.close(self._held.descriptors.pop())

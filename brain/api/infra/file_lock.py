"""Reentrant file locks shared by threads and processes on one host."""

from __future__ import annotations

import fcntl
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()
_held = threading.local()


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Lock a stable sidecar, even when the protected file is replaced atomically."""
    path = Path(path)
    key = str(path.absolute())
    with _locks_guard:
        thread_lock = _locks.setdefault(key, threading.RLock())
    with thread_lock:
        held = getattr(_held, "paths", None)
        if held is None:
            held = _held.paths = set()
        if key in held:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_name(path.name + ".lock").open("a") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            held.add(key)
            try:
                yield
            finally:
                held.remove(key)
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path: Path, content: str) -> None:
    """Publish complete UTF-8 content while preserving existing permissions."""
    path = Path(path)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".write-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

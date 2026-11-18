"""Memory writeback never runs on the reply path, even though finalize now runs in a worker thread."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from core import chat_service


def test_scheduling_from_a_plain_thread_returns_before_the_write(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def slow_write(**kwargs):
        started.set()
        release.wait(2)

    monkeypatch.setattr(chat_service, "write_summary_and_reindex", slow_write)
    context = SimpleNamespace(persona_id="default", project_id="p", session_id="s", user_message="hi")
    elapsed: list[float] = []

    def finalize_like() -> None:
        begin = time.monotonic()
        chat_service._schedule_memory_writes(context, "hello")
        elapsed.append(time.monotonic() - begin)

    worker = threading.Thread(target=finalize_like)
    worker.start()
    worker.join(2)
    release.set()

    assert started.wait(2)
    assert elapsed and elapsed[0] < 0.5

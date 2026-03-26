"""Tests for SessionStore — inflight guard, dedup window, interrupt reset."""

from __future__ import annotations

import threading
import time

import pytest

from memory.session_store import (
    DuplicateMessageError,
    InflightError,
    SessionStore,
)


@pytest.fixture()
def store(tmp_path):
    db_path = str(tmp_path / "test_sessions.db")
    return SessionStore(db_path=db_path)


# ------------------------------------------------------------------
# Basic session CRUD
# ------------------------------------------------------------------


def test_create_and_retrieve_session(store: SessionStore):
    state = store.get_or_create_session("s1", "default")
    assert state.session_id == "s1"
    assert state.persona_id == "default"
    assert state.messages == []


def test_append_and_list_messages(store: SessionStore):
    store.get_or_create_session("s1", "default")
    store.append_message("s1", "default", "user", "hello")
    store.append_message("s1", "default", "assistant", "hi")
    messages = store.list_messages("s1", "default")
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


def test_delete_session_cascade(store: SessionStore):
    store.get_or_create_session("s1", "default")
    store.append_message("s1", "default", "user", "hello")
    assert store.delete_session("s1") is True
    assert store.list_messages("s1") == []


def test_session_auto_prune(tmp_path):
    """Messages beyond max_session_rounds * 2 are pruned on append."""
    import memory.session_store as mod

    original = mod.get_settings
    try:
        mod.get_settings = lambda: _fake_settings(max_session_rounds=2)
        store = SessionStore(db_path=str(tmp_path / "prune.db"))
        store.get_or_create_session("s1", "default")
        for i in range(10):
            store.append_message("s1", "default", "user", f"msg-{i}")
        messages = store.list_messages("s1", "default")
        assert len(messages) == 10

        mod.get_settings = lambda: _fake_settings(max_session_rounds=1)
        store2 = SessionStore(db_path=str(tmp_path / "prune2.db"))
        store2.get_or_create_session("s2", "default")
        for i in range(30):
            store2.append_message("s2", "default", "user", f"msg-{i}")
        messages = store2.list_messages("s2", "default")
        # max_messages = max(1 * 2, 20) = 20
        assert len(messages) == 20
    finally:
        mod.get_settings = original


# ------------------------------------------------------------------
# Inflight guard
# ------------------------------------------------------------------


def test_acquire_inflight_succeeds_once(store: SessionStore):
    store.acquire_inflight("s1")
    store.release_inflight("s1")


def test_acquire_inflight_blocks_concurrent(store: SessionStore):
    store.acquire_inflight("s1")
    with pytest.raises(InflightError, match="已有進行中的回應"):
        store.acquire_inflight("s1")
    store.release_inflight("s1")


def test_acquire_inflight_independent_sessions(store: SessionStore):
    """Different sessions don't block each other."""
    store.acquire_inflight("s1")
    store.acquire_inflight("s2")  # should not raise
    store.release_inflight("s1")
    store.release_inflight("s2")


def test_release_inflight_idempotent(store: SessionStore):
    """Releasing when not held does not raise."""
    store.release_inflight("s1")
    store.release_inflight("s1")


def test_inflight_guard_threaded(store: SessionStore):
    """Verify inflight guard works across threads."""
    results: list[str] = []
    barrier = threading.Barrier(2, timeout=5)

    def worker(name: str):
        barrier.wait()
        try:
            store.acquire_inflight("s1")
            results.append(f"{name}:acquired")
            time.sleep(0.1)
            store.release_inflight("s1")
        except InflightError:
            results.append(f"{name}:blocked")

    t1 = threading.Thread(target=worker, args=("A",))
    t2 = threading.Thread(target=worker, args=("B",))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    acquired = [r for r in results if r.endswith(":acquired")]
    blocked = [r for r in results if r.endswith(":blocked")]
    assert len(acquired) == 1
    assert len(blocked) == 1


# ------------------------------------------------------------------
# Dedup window
# ------------------------------------------------------------------


def test_dedup_accepts_first_message(store: SessionStore):
    store.check_dedup("s1", "hello")  # should not raise


def test_dedup_rejects_duplicate_within_window(store: SessionStore):
    store.check_dedup("s1", "hello")
    with pytest.raises(DuplicateMessageError, match="重複訊息"):
        store.check_dedup("s1", "hello")


def test_dedup_accepts_different_text(store: SessionStore):
    store.check_dedup("s1", "hello")
    store.check_dedup("s1", "world")  # should not raise


def test_dedup_accepts_same_text_different_sessions(store: SessionStore):
    store.check_dedup("s1", "hello")
    store.check_dedup("s2", "hello")  # should not raise


def test_dedup_accepts_after_window_expires(store: SessionStore, monkeypatch):
    import memory.session_store as mod

    monkeypatch.setattr(mod, "_DEDUP_WINDOW_SECONDS", 0.05)
    store.check_dedup("s1", "hello")
    time.sleep(0.06)
    store.check_dedup("s1", "hello")  # should not raise


# ------------------------------------------------------------------
# Interrupt-safe reset
# ------------------------------------------------------------------


def test_interrupt_releases_inflight(store: SessionStore):
    store.acquire_inflight("s1")
    store.interrupt_session("s1")
    # Should be able to acquire again
    store.acquire_inflight("s1")
    store.release_inflight("s1")


def test_interrupt_clears_dedup(store: SessionStore):
    store.check_dedup("s1", "hello")
    store.interrupt_session("s1")
    # Same message should be accepted after interrupt
    store.check_dedup("s1", "hello")  # should not raise


def test_interrupt_when_idle_is_safe(store: SessionStore):
    """Interrupting a session with nothing in-flight should not raise."""
    store.interrupt_session("s1")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


class _FakeSettings:
    def __init__(self, **kwargs):
        defaults = {
            "max_session_rounds": 100,
            "max_session_ttl_minutes": 30 * 24 * 60,
            "session_db_resolved_path": "/tmp/test.db",
            "memory_maintenance_interval_seconds": 300,
            "memory_decay_rate_per_day": 0.005,
            "memory_merge_similarity_threshold": 0.92,
            "memory_importance_weight": 0.03,
            "request_rate_limit_per_minute": 60,
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


def _fake_settings(**kwargs):
    return _FakeSettings(**kwargs)

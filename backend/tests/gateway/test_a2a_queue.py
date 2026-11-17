"""Unit tests for SQLite WAL A2A work queue and idempotency."""

from pathlib import Path
import pytest

from app.gateway.a2a_queue import A2AWorkQueue


def test_queue_enqueue_and_deduplication(tmp_path: Path):
    db_path = tmp_path / "work.db"
    q = A2AWorkQueue(db_path)

    # 1. Enqueue new event
    inserted = q.enqueue_event(
        hub_scope="test-hub",
        sequence=1,
        task_id="task-1",
        requester_agent_id="agent-peer",
        message="Hello",
    )
    assert inserted is True

    # 2. Duplicate sequence rejected
    dup_seq = q.enqueue_event(
        hub_scope="test-hub",
        sequence=1,
        task_id="task-2",
        requester_agent_id="agent-peer",
        message="Hello again",
    )
    assert dup_seq is False

    # 3. Duplicate task_id rejected
    dup_task = q.enqueue_event(
        hub_scope="test-hub",
        sequence=2,
        task_id="task-1",
        requester_agent_id="agent-peer",
        message="Different seq same task",
    )
    assert dup_task is False


def test_queue_status_transitions(tmp_path: Path):
    db_path = tmp_path / "work.db"
    q = A2AWorkQueue(db_path)

    q.enqueue_event(
        hub_scope="test-hub",
        sequence=5,
        task_id="task-5",
        requester_agent_id="agent-peer",
        message="Process this",
    )

    # Mark ACK
    q.mark_ack_dispatched("test-hub", 5)

    events = q.get_unprocessed_events("test-hub")
    assert len(events) == 1
    assert events[0]["sequence"] == 5
    assert events[0]["status"] == "ACKNOWLEDGED"

    event_id = events[0]["id"]
    q.record_processing_start(event_id)
    q.record_completed(event_id, reply_task_id="reply-123", reply_message="Done")

    # Completed events no longer in unprocessed
    remaining = q.get_unprocessed_events("test-hub")
    assert len(remaining) == 0

    assert q.get_last_processed_sequence("test-hub") == 5


def test_queue_outbound_idempotency(tmp_path: Path):
    db_path = tmp_path / "work.db"
    q = A2AWorkQueue(db_path)

    ok1 = q.record_outbound_task(
        task_id="out-1",
        idempotency_key="reply-task-1",
        target_agent_id="peer-1",
        message="First reply",
    )
    assert ok1 is True

    # PENDING 狀態允許重試（程序崩潰後重啟的 crash-recovery 場景）
    ok2 = q.record_outbound_task(
        task_id="out-2",
        idempotency_key="reply-task-1",
        target_agent_id="peer-1",
        message="Second reply attempt",
    )
    assert ok2 is True

    # 標記為已送出後，重複 key 才真正被擋掉
    q.mark_outbound_sent("reply-task-1")
    ok3 = q.record_outbound_task(
        task_id="out-3",
        idempotency_key="reply-task-1",
        target_agent_id="peer-1",
        message="Third attempt after sent",
    )
    assert ok3 is False


def test_record_completed_and_suppressed_enforce_processing_owner(tmp_path: Path):
    import sqlite3

    db_path = tmp_path / "work.db"
    q = A2AWorkQueue(db_path)

    q.enqueue_event("hub-1", 1, "t-comp", "peer-a", "msg-1")
    q.mark_ack_dispatched("hub-1", 1)
    q.enqueue_event("hub-1", 2, "t-supp", "peer-a", "msg-2")
    q.mark_ack_dispatched("hub-1", 2)

    ev1, ev2 = q.get_unprocessed_events("hub-1", limit=10)
    assert q.record_processing_start(ev1["id"], worker_id="worker-old") is True
    assert q.record_processing_start(ev2["id"], worker_id="worker-old") is True

    # New leader recovers and takes ownership
    assert q.requeue_processing_events("hub-1") == 2
    assert q.record_processing_start(ev1["id"], worker_id="worker-new") is True
    assert q.record_processing_start(ev2["id"], worker_id="worker-new") is True

    # Stale worker updates must be rejected
    assert q.record_completed(ev1["id"], "stale-r", "stale", worker_id="worker-old") is False
    assert q.record_suppressed(ev2["id"], "token", worker_id="worker-old") is False

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        r1 = conn.execute("SELECT status, processing_owner FROM a2a_inbox_events WHERE id = ?", (ev1["id"],)).fetchone()
        r2 = conn.execute("SELECT status, processing_owner FROM a2a_inbox_events WHERE id = ?", (ev2["id"],)).fetchone()
        assert r1["status"] == "PROCESSING" and r1["processing_owner"] == "worker-new"
        assert r2["status"] == "PROCESSING" and r2["processing_owner"] == "worker-new"

    # Current owner succeeds
    assert q.record_completed(ev1["id"], "new-r", "ok", worker_id="worker-new") is True
    assert q.record_suppressed(ev2["id"], "token", worker_id="worker-new") is True


def test_record_failed_sets_exponential_backoff_and_respects_10m_window(tmp_path: Path):
    from datetime import datetime, timezone
    import sqlite3

    db_path = tmp_path / "work.db"
    q = A2AWorkQueue(db_path, retry_window_seconds=600.0, max_backoff_seconds=60.0)
    q.enqueue_event("hub-1", 1, "t-backoff", "peer-a", "msg-backoff")
    q.mark_ack_dispatched("hub-1", 1)
    ev_id = q.get_unprocessed_events("hub-1")[0]["id"]

    observed_delays: list[float] = []
    # Attempts 1..7 (> old 5-attempt cutoff) must continue retrying with 2,4,8,16,32,60,60s backoff
    for attempt in range(1, 8):
        assert q.record_processing_start(ev_id, worker_id="w-1") is True
        assert q.record_failed(ev_id, f"err-{attempt}", worker_id="w-1") is True
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT status, attempts, next_retry_at, first_failed_at, updated_at FROM a2a_inbox_events WHERE id = ?",
                (ev_id,),
            ).fetchone()
            assert row["status"] == "ACKNOWLEDGED"
            assert row["attempts"] == attempt
            assert row["first_failed_at"] is not None
            assert row["next_retry_at"] is not None
            delta = (
                datetime.fromisoformat(row["next_retry_at"])
                - datetime.fromisoformat(row["updated_at"])
            ).total_seconds()
            observed_delays.append(delta)
            conn.execute("UPDATE a2a_inbox_events SET next_retry_at = NULL WHERE id = ?", (ev_id,))
            conn.commit()

    expected = [2, 4, 8, 16, 32, 60, 60]
    for obs, exp in zip(observed_delays, expected):
        assert exp - 0.5 <= obs <= exp + 0.5

    # Once first_failed_at exceeds the 10-minute total retry window, record_failed transitions to FAILED
    expired_iso = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - 605.0, tz=timezone.utc).isoformat()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("UPDATE a2a_inbox_events SET first_failed_at = ? WHERE id = ?", (expired_iso, ev_id))
        conn.commit()

    assert q.record_processing_start(ev_id, worker_id="w-1") is True
    assert q.record_failed(ev_id, "err-expired", worker_id="w-1") is True
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status, attempts, next_retry_at FROM a2a_inbox_events WHERE id = ?", (ev_id,)).fetchone()
        assert row["status"] == "FAILED"
        assert row["attempts"] == 8
        assert row["next_retry_at"] is None


def test_record_rate_limited_caps_delay_at_60s_and_expires_after_10m_window(tmp_path: Path):
    from datetime import datetime, timezone
    import sqlite3

    db_path = tmp_path / "work.db"
    q = A2AWorkQueue(db_path, retry_window_seconds=600.0, max_backoff_seconds=60.0)
    q.enqueue_event("hub-1", 1, "t-rl-cap", "peer-a", "msg-rl")
    q.mark_ack_dispatched("hub-1", 1)
    ev_id = q.get_unprocessed_events("hub-1")[0]["id"]

    # Repeated 429s do not decrement attempts and grow exponentially when Retry-After is small.
    assert q.record_processing_start(ev_id, worker_id="w-1") is True
    assert q.record_rate_limited(ev_id, 0.5, worker_id="w-1") is True
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, attempts, next_retry_at, first_failed_at, updated_at FROM a2a_inbox_events WHERE id = ?",
            (ev_id,),
        ).fetchone()
        assert row["status"] == "ACKNOWLEDGED"
        assert row["attempts"] == 1
        assert row["first_failed_at"] is not None
        delta1 = (datetime.fromisoformat(row["next_retry_at"]) - datetime.fromisoformat(row["updated_at"])).total_seconds()
        assert 1.8 <= delta1 <= 2.2

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("UPDATE a2a_inbox_events SET next_retry_at = NULL WHERE id = ?", (ev_id,))
        conn.commit()
    assert q.record_processing_start(ev_id, worker_id="w-1") is True
    assert q.record_rate_limited(ev_id, 0.5, worker_id="w-1") is True
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, attempts, next_retry_at, updated_at FROM a2a_inbox_events WHERE id = ?",
            (ev_id,),
        ).fetchone()
        assert row["status"] == "ACKNOWLEDGED"
        assert row["attempts"] == 2
        delta2 = (datetime.fromisoformat(row["next_retry_at"]) - datetime.fromisoformat(row["updated_at"])).total_seconds()
        assert 3.8 <= delta2 <= 4.2

    # Large Retry-After is still capped at max_backoff_seconds (60s).
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("UPDATE a2a_inbox_events SET next_retry_at = NULL WHERE id = ?", (ev_id,))
        conn.commit()
    assert q.record_processing_start(ev_id, worker_id="w-1") is True
    assert q.record_rate_limited(ev_id, 86400.0, worker_id="w-1") is True
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, attempts, next_retry_at, first_failed_at, updated_at FROM a2a_inbox_events WHERE id = ?",
            (ev_id,),
        ).fetchone()
        assert row["status"] == "ACKNOWLEDGED"
        assert row["attempts"] == 3
        assert row["first_failed_at"] is not None
        delta3 = (datetime.fromisoformat(row["next_retry_at"]) - datetime.fromisoformat(row["updated_at"])).total_seconds()
        assert 59.0 <= delta3 <= 60.5

    # Exceed 10m window -> rate-limited row transitions to FAILED
    expired_iso = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - 605.0, tz=timezone.utc).isoformat()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("UPDATE a2a_inbox_events SET next_retry_at = NULL, first_failed_at = ? WHERE id = ?", (expired_iso, ev_id))
        conn.commit()
    # Direct get_unprocessed_events also expires overdue ACKNOWLEDGED rows
    assert q.get_unprocessed_events("hub-1") == []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status, next_retry_at FROM a2a_inbox_events WHERE id = ?", (ev_id,)).fetchone()
        assert row["status"] == "FAILED"
        assert row["next_retry_at"] is None


def test_requeue_processing_events_stamps_first_failed_at_expires_old_and_excludes_active(tmp_path: Path):
    from datetime import datetime, timezone
    import sqlite3

    db_path = tmp_path / "work.db"
    q = A2AWorkQueue(db_path, retry_window_seconds=600.0, max_backoff_seconds=60.0)
    q.enqueue_event("hub-1", 1, "t-fresh", "peer-a", "msg-1")
    q.enqueue_event("hub-1", 2, "t-active", "peer-a", "msg-2")
    q.enqueue_event("hub-1", 3, "t-old-created", "peer-a", "msg-3")
    q.enqueue_event("hub-1", 4, "t-legacy", "peer-a", "msg-4")
    for seq in (1, 2, 3, 4):
        q.mark_ack_dispatched("hub-1", seq)

    rows = {r["task_id"]: r["id"] for r in q.get_unprocessed_events("hub-1")}
    assert q.record_processing_start(rows["t-fresh"], worker_id="w-dead") is True
    assert q.record_processing_start(rows["t-active"], worker_id="w-live") is True
    assert q.record_processing_start(rows["t-old-created"], worker_id="w-dead") is True
    assert q.record_processing_start(rows["t-legacy"], worker_id="w-dead") is True

    old_iso = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - 700.0, tz=timezone.utc).isoformat()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE a2a_inbox_events SET created_at = ?, updated_at = ? WHERE id = ?",
            (old_iso, old_iso, rows["t-old-created"]),
        )
        conn.execute(
            "UPDATE a2a_inbox_events SET attempts = 5, first_failed_at = NULL WHERE id = ?",
            (rows["t-legacy"],),
        )
        conn.commit()

    # Requeue while excluding w-live's active event
    requeued = q.requeue_processing_events(
        "hub-1",
        exclude_worker_id="w-live",
        exclude_active_event_ids={rows["t-active"]},
    )
    assert requeued == 1

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        r_fresh = conn.execute("SELECT * FROM a2a_inbox_events WHERE id = ?", (rows["t-fresh"],)).fetchone()
        r_active = conn.execute("SELECT * FROM a2a_inbox_events WHERE id = ?", (rows["t-active"],)).fetchone()
        r_old = conn.execute("SELECT * FROM a2a_inbox_events WHERE id = ?", (rows["t-old-created"],)).fetchone()
        r_legacy = conn.execute("SELECT * FROM a2a_inbox_events WHERE id = ?", (rows["t-legacy"],)).fetchone()

        assert r_fresh["status"] == "ACKNOWLEDGED"
        assert r_fresh["first_failed_at"] is not None
        assert r_active["status"] == "PROCESSING"
        assert r_active["processing_owner"] == "w-live"
        assert r_old["status"] == "FAILED"
        assert "retry window" in (r_old["error"] or "").lower()
        assert r_legacy["status"] == "FAILED"
        assert "retry window" in (r_legacy["error"] or "").lower()

    # If the stamped first_failed_at is now older than 10m, another handoff finalizes it to FAILED
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE a2a_inbox_events SET first_failed_at = ?, status = 'PROCESSING', processing_owner = 'w-2' WHERE id = ?",
            (old_iso, rows["t-fresh"]),
        )
        conn.commit()
    assert (
        q.requeue_processing_events(
            "hub-1",
            exclude_worker_id="w-live",
            exclude_active_event_ids={rows["t-active"]},
        )
        == 0
    )
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        r_fresh2 = conn.execute("SELECT status FROM a2a_inbox_events WHERE id = ?", (rows["t-fresh"],)).fetchone()
        assert r_fresh2["status"] == "FAILED"

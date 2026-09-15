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

    # Duplicate idempotency key returns False (suppressed)
    ok2 = q.record_outbound_task(
        task_id="out-2",
        idempotency_key="reply-task-1",
        target_agent_id="peer-1",
        message="Second reply attempt",
    )
    assert ok2 is False

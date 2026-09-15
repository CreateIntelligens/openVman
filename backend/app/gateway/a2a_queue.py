"""SQLite WAL work queue for A2A inbox events, delivery state, and outbound idempotency."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Any

logger = logging.getLogger("backend.gateway.a2a_queue")


class A2AWorkQueue:
    """Crash-safe SQLite WAL queue ensuring enqueue-before-ACK ordering and deduplication."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize database with WAL journal mode and schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_conn() as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS a2a_inbox_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hub_scope TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    task_id TEXT NOT NULL,
                    context_id TEXT,
                    requester_agent_id TEXT NOT NULL,
                    group_id TEXT,
                    message TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'RECEIVED',
                    ack_dispatched_at TEXT,
                    ack_attempts INTEGER NOT NULL DEFAULT 0,
                    next_ack_at TEXT,
                    reply_task_id TEXT,
                    reply_message TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(hub_scope, sequence),
                    UNIQUE(hub_scope, task_id)
                );

                CREATE INDEX IF NOT EXISTS idx_a2a_inbox_status ON a2a_inbox_events(status);
                CREATE INDEX IF NOT EXISTS idx_a2a_inbox_seq ON a2a_inbox_events(hub_scope, sequence);

                CREATE TABLE IF NOT EXISTS a2a_outbound_tasks (
                    task_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    target_agent_id TEXT NOT NULL,
                    context_id TEXT,
                    message TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    created_at TEXT NOT NULL
                );
                """
            )
            for statement in (
                "ALTER TABLE a2a_inbox_events ADD COLUMN ack_attempts INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE a2a_inbox_events ADD COLUMN next_ack_at TEXT",
            ):
                try:
                    conn.execute(statement)
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            conn.commit()
        logger.debug("Initialized A2A SQLite queue at %s", self.db_path)

    def enqueue_event(
        self,
        hub_scope: str,
        sequence: int,
        task_id: str,
        requester_agent_id: str,
        message: str,
        context_id: str | None = None,
        group_id: str | None = None,
    ) -> bool:
        """Atomically commit an incoming task before ACK dispatch. Returns True if inserted, False if duplicate."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO a2a_inbox_events (
                        hub_scope, sequence, task_id, context_id, requester_agent_id,
                        group_id, message, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'RECEIVED', ?, ?)
                    """,
                    (
                        hub_scope,
                        sequence,
                        task_id,
                        context_id,
                        requester_agent_id,
                        group_id,
                        message,
                        now,
                        now,
                    ),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Duplicate sequence or taskId detected
                logger.debug(
                    "Duplicate A2A event ignored (hub=%s, seq=%d, task=%s)",
                    hub_scope,
                    sequence,
                    task_id,
                )
                return False

    def mark_ack_dispatched(self, hub_scope: str, sequence: int) -> None:
        """Mark sequence as acknowledged."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE a2a_inbox_events
                SET ack_dispatched_at = ?,
                    ack_attempts = ack_attempts + 1,
                    next_ack_at = NULL,
                    status = CASE WHEN status = 'RECEIVED' THEN 'ACKNOWLEDGED' ELSE status END,
                    updated_at = ?
                WHERE hub_scope = ? AND sequence = ?
                """,
                (now, now, hub_scope, sequence),
            )
            conn.commit()

    def record_ack_failure(self, hub_scope: str, sequence: int, retry_after_seconds: float = 1.0) -> None:
        """Record a failed ACK without advancing the durable replay cursor."""
        now = datetime.now(timezone.utc)
        next_ack = (now.timestamp() + max(0.1, retry_after_seconds))
        next_ack_at = datetime.fromtimestamp(next_ack, tz=timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE a2a_inbox_events
                SET ack_attempts = ack_attempts + 1, next_ack_at = ?, updated_at = ?
                WHERE hub_scope = ? AND sequence = ? AND ack_dispatched_at IS NULL
                """,
                (next_ack_at, now.isoformat(), hub_scope, sequence),
            )
            conn.commit()

    def get_pending_ack_events(self, hub_scope: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return durable events that still need an ACK."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM a2a_inbox_events
                WHERE hub_scope = ?
                  AND ack_dispatched_at IS NULL
                  AND (next_ack_at IS NULL OR next_ack_at <= ?)
                  AND ack_attempts < 10
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (hub_scope, now, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_unprocessed_events(self, hub_scope: str, limit: int = 4) -> list[dict[str, Any]]:
        """Get pending events ready for LLM processing."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM a2a_inbox_events
                WHERE hub_scope = ? AND status = 'ACKNOWLEDGED' AND attempts < 5
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (hub_scope, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def record_processing_start(self, event_id: int) -> None:
        """Increment attempt counter and transition to PROCESSING state."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE a2a_inbox_events
                SET attempts = attempts + 1, status = 'PROCESSING', updated_at = ?
                WHERE id = ?
                """,
                (now, event_id),
            )
            conn.commit()

    def record_completed(
        self,
        event_id: int,
        reply_task_id: str | None = None,
        reply_message: str | None = None,
    ) -> None:
        """Mark event as completed with optional reply audit trail."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE a2a_inbox_events
                SET status = 'COMPLETED', reply_task_id = ?, reply_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (reply_task_id, reply_message, now, event_id),
            )
            conn.commit()

    def record_suppressed(self, event_id: int, reason: str = "anti-echo") -> None:
        """Mark event as suppressed (no reciprocal reply sent)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE a2a_inbox_events
                SET status = 'SUPPRESSED', error = ?, updated_at = ?
                WHERE id = ?
                """,
                (f"Suppressed: {reason}", now, event_id),
            )
            conn.commit()

    def record_failed(self, event_id: int, error_message: str) -> None:
        """Record failure and mark terminal if attempts >= 5."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE a2a_inbox_events
                SET error = ?,
                    status = CASE WHEN attempts >= 5 THEN 'FAILED' ELSE 'ACKNOWLEDGED' END,
                    updated_at = ?
                WHERE id = ?
                """,
                (error_message[:500], now, event_id),
            )
            conn.commit()

    def record_outbound_task(
        self,
        task_id: str,
        idempotency_key: str,
        target_agent_id: str,
        message: str,
        context_id: str | None = None,
    ) -> bool:
        """Durable idempotency record for outbound task replies. Returns False if duplicate."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO a2a_outbound_tasks (
                        task_id, idempotency_key, target_agent_id, context_id, message, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
                    """,
                    (task_id, idempotency_key, target_agent_id, context_id, message, now),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT status FROM a2a_outbound_tasks WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                # A failed reservation may be retried with the same idempotency key;
                # a sent task must remain a no-op after a crash/replay.
                return bool(row and row["status"] != "SENT")

    def mark_outbound_sent(self, idempotency_key: str) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE a2a_outbound_tasks SET status = 'SENT' WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            conn.commit()

    def get_last_processed_sequence(self, hub_scope: str) -> int:
        """Get latest committed sequence for resuming SSE stream."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT sequence, ack_dispatched_at FROM a2a_inbox_events
                WHERE hub_scope = ?
                ORDER BY sequence ASC
                """,
                (hub_scope,),
            )
            last = 0
            for row in cursor.fetchall():
                if row["ack_dispatched_at"] is None:
                    break
                last = int(row["sequence"])
            return last

    def prune_terminal_events(self, retention_days: int = 30) -> int:
        """Delete old terminal records while retaining active/retryable work."""
        cutoff = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() - max(1, retention_days) * 86400,
            tz=timezone.utc,
        ).isoformat()
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                DELETE FROM a2a_inbox_events
                WHERE status IN ('COMPLETED', 'SUPPRESSED', 'FAILED') AND updated_at < ?
                """,
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.execute(
                "DELETE FROM a2a_outbound_tasks WHERE created_at < ? AND status IN ('SENT', 'FAILED')",
                (cutoff,),
            )
            conn.commit()
            return deleted

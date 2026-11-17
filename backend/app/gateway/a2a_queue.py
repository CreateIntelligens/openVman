"""SQLite WAL work queue for A2A inbox events, delivery state, and outbound idempotency."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import logging
from pathlib import Path
import sqlite3
from typing import Any

logger = logging.getLogger("backend.gateway.a2a_queue")


class A2AWorkQueue:
    """Crash-safe SQLite WAL queue ensuring enqueue-before-ACK ordering and deduplication."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        retry_window_seconds: float = 600.0,
        max_backoff_seconds: float = 60.0,
    ):
        self.db_path = Path(db_path)
        self.retry_window_seconds = max(1.0, float(retry_window_seconds))
        self.max_backoff_seconds = max(1.0, float(max_backoff_seconds))
        self._closing = False
        self._shutdown_busy_timeout_ms = 250
        self._init_db()

    def begin_shutdown(self, busy_timeout_ms: int = 250) -> None:
        """Use a short SQLite busy_timeout so shutdown paths cannot block for 10s."""
        self._shutdown_busy_timeout_ms = max(50, int(busy_timeout_ms))
        self._closing = True

    def reset_shutdown(self) -> None:
        self._closing = False

    @contextmanager
    def _get_conn(self, *, busy_timeout_ms: int | None = None) -> Iterator[sqlite3.Connection]:
        effective_ms = (
            busy_timeout_ms
            if busy_timeout_ms is not None
            else (self._shutdown_busy_timeout_ms if self._closing else 10000)
        )
        conn = sqlite3.connect(str(self.db_path), timeout=max(0.1, effective_ms / 1000.0))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute(f"PRAGMA busy_timeout = {int(effective_ms)};")
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _is_retry_deadline_expired(self, first_failed_at: str | None, now_dt: datetime) -> bool:
        if not first_failed_at:
            return False
        try:
            first_dt = datetime.fromisoformat(str(first_failed_at))
        except ValueError:
            return False
        if first_dt.tzinfo is None:
            first_dt = first_dt.replace(tzinfo=timezone.utc)
        return (now_dt - first_dt).total_seconds() >= self.retry_window_seconds

    def _init_db(self) -> None:
        """Initialize database with WAL journal mode and schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.db_path.with_name(self.db_path.name + ".init.lock")
        with open(lock_path, "a", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
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
                            next_retry_at TEXT,
                            first_failed_at TEXT,
                            processing_owner TEXT,
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
                        "ALTER TABLE a2a_inbox_events ADD COLUMN next_retry_at TEXT",
                        "ALTER TABLE a2a_inbox_events ADD COLUMN first_failed_at TEXT",
                        "ALTER TABLE a2a_inbox_events ADD COLUMN processing_owner TEXT",
                    ):
                        try:
                            conn.execute(statement)
                        except sqlite3.OperationalError as exc:
                            if "duplicate column name" not in str(exc).lower():
                                raise
                    conn.commit()
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
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
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        # Give instant-ACK 5s before _ack_worker_loop considers retrying this row.
        initial_next_ack_at = datetime.fromtimestamp(
            now_dt.timestamp() + 5.0,
            tz=timezone.utc,
        ).isoformat()
        with self._get_conn() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO a2a_inbox_events (
                        hub_scope, sequence, task_id, context_id, requester_agent_id,
                        group_id, message, status, next_ack_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'RECEIVED', ?, ?, ?)
                    """,
                    (
                        hub_scope,
                        sequence,
                        task_id,
                        context_id,
                        requester_agent_id,
                        group_id,
                        message,
                        initial_next_ack_at,
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

    def _is_row_expired_for_requeue(self, row: sqlite3.Row, now_dt: datetime) -> bool:
        first_failed = row["first_failed_at"]
        if first_failed and self._is_retry_deadline_expired(first_failed, now_dt):
            return True
        if self._is_retry_deadline_expired(row["created_at"], now_dt):
            return True
        if not first_failed and int(row["attempts"] or 0) >= 5:
            return True
        return False

    def _requeue_rows(
        self,
        conn: sqlite3.Connection,
        rows: list[sqlite3.Row],
        now_dt: datetime,
        now: str,
        *,
        expired_error: str,
    ) -> int:
        expired_ids: list[int] = []
        requeue_ids: list[int] = []
        for row in rows:
            ev_id = int(row["id"])
            if self._is_row_expired_for_requeue(row, now_dt):
                expired_ids.append(ev_id)
            else:
                requeue_ids.append(ev_id)

        if expired_ids:
            placeholders = ",".join("?" for _ in expired_ids)
            conn.execute(
                f"""
                UPDATE a2a_inbox_events
                SET status = 'FAILED',
                    next_retry_at = NULL,
                    processing_owner = NULL,
                    error = COALESCE(error, ?),
                    updated_at = ?
                WHERE id IN ({placeholders})
                """,
                [expired_error, now, *expired_ids],
            )
        if requeue_ids:
            placeholders = ",".join("?" for _ in requeue_ids)
            conn.execute(
                f"""
                UPDATE a2a_inbox_events
                SET status = 'ACKNOWLEDGED',
                    processing_owner = NULL,
                    first_failed_at = COALESCE(first_failed_at, ?),
                    updated_at = ?
                WHERE id IN ({placeholders})
                """,
                [now, now, *requeue_ids],
            )
        return len(requeue_ids)

    def get_unprocessed_events(self, hub_scope: str, limit: int = 4) -> list[dict[str, Any]]:
        """Get pending events ready for LLM processing, finalizing expired retry windows."""
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self._get_conn() as conn:
            candidates = conn.execute(
                """
                SELECT * FROM a2a_inbox_events
                WHERE hub_scope = ?
                  AND status = 'ACKNOWLEDGED'
                  AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY sequence ASC
                """,
                (hub_scope, now),
            ).fetchall()

            expired_ids: list[int] = []
            ready: list[dict[str, Any]] = []
            for row in candidates:
                if self._is_retry_deadline_expired(row["first_failed_at"], now_dt):
                    expired_ids.append(int(row["id"]))
                elif len(ready) < limit:
                    ready.append(dict(row))

            if expired_ids:
                placeholders = ",".join("?" for _ in expired_ids)
                conn.execute(
                    f"""
                    UPDATE a2a_inbox_events
                    SET status = 'FAILED',
                        next_retry_at = NULL,
                        processing_owner = NULL,
                        error = COALESCE(error, ?),
                        updated_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    [f"Exceeded maximum retry window ({int(self.retry_window_seconds)}s)", now, *expired_ids],
                )
                conn.commit()
            return ready

    def record_processing_start(self, event_id: int, worker_id: str | None = None) -> bool:
        """Increment attempt counter, bind processing_owner, and transition to PROCESSING state."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                UPDATE a2a_inbox_events
                SET attempts = attempts + 1,
                    status = 'PROCESSING',
                    processing_owner = ?,
                    updated_at = ?
                WHERE id = ? AND status = 'ACKNOWLEDGED'
                """,
                (worker_id, now, event_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def record_reply_prepared(
        self,
        event_id: int,
        reply_task_id: str,
        reply_message: str,
        *,
        worker_id: str | None = None,
    ) -> bool:
        """Persist generated reply_task_id and reply_message before outbound dispatch."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            if worker_id is None:
                cursor = conn.execute(
                    """
                    UPDATE a2a_inbox_events
                    SET reply_task_id = ?, reply_message = ?, updated_at = ?
                    WHERE id = ? AND status = 'PROCESSING'
                    """,
                    (reply_task_id, reply_message, now, event_id),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE a2a_inbox_events
                    SET reply_task_id = ?, reply_message = ?, updated_at = ?
                    WHERE id = ? AND status = 'PROCESSING' AND processing_owner = ?
                    """,
                    (reply_task_id, reply_message, now, event_id, worker_id),
                )
            conn.commit()
            return cursor.rowcount > 0

    def revert_processing_start(self, event_id: int, worker_id: str | None = None) -> bool:
        """Return an interrupted PROCESSING event to ACKNOWLEDGED without consuming an attempt."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            if worker_id is None:
                cursor = conn.execute(
                    """
                    UPDATE a2a_inbox_events
                    SET status = 'ACKNOWLEDGED',
                        attempts = MAX(0, attempts - 1),
                        processing_owner = NULL,
                        updated_at = ?
                    WHERE id = ? AND status = 'PROCESSING'
                    """,
                    (now, event_id),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE a2a_inbox_events
                    SET status = 'ACKNOWLEDGED',
                        attempts = MAX(0, attempts - 1),
                        processing_owner = NULL,
                        updated_at = ?
                    WHERE id = ? AND status = 'PROCESSING' AND processing_owner = ?
                    """,
                    (now, event_id, worker_id),
                )
            conn.commit()
            return cursor.rowcount > 0

    def requeue_processing_events(
        self,
        hub_scope: str,
        *,
        exclude_worker_id: str | None = None,
        exclude_active_event_ids: set[int] | list[int] | tuple[int, ...] = (),
    ) -> int:
        """Recover abandoned PROCESSING rows; preserve active self-owned rows if excluded and fail expired/legacy rows."""
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        active_set = {int(eid) for eid in exclude_active_event_ids}
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, attempts, first_failed_at, created_at, processing_owner FROM a2a_inbox_events
                WHERE hub_scope = ? AND status = 'PROCESSING'
                """,
                (hub_scope,),
            ).fetchall()
            targets = [
                row
                for row in rows
                if not (
                    exclude_worker_id is not None
                    and row["processing_owner"] == exclude_worker_id
                    and int(row["id"]) in active_set
                )
            ]
            if not targets:
                return 0
            requeued = self._requeue_rows(
                conn,
                targets,
                now_dt,
                now,
                expired_error=f"Exceeded maximum retry window ({int(self.retry_window_seconds)}s) after leader interruption",
            )
            conn.commit()
            return requeued

    def requeue_orphaned_local_events(
        self,
        hub_scope: str,
        worker_id: str,
        active_event_ids: set[int] | list[int] | tuple[int, ...] = (),
    ) -> int:
        """Recover PROCESSING rows owned by this worker that no longer have a running task."""
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        active_set = {int(eid) for eid in active_event_ids}
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, attempts, first_failed_at, created_at FROM a2a_inbox_events
                WHERE hub_scope = ? AND status = 'PROCESSING' AND processing_owner = ?
                """,
                (hub_scope, worker_id),
            ).fetchall()
            orphaned = [row for row in rows if int(row["id"]) not in active_set]
            if not orphaned:
                return 0
            requeued = self._requeue_rows(
                conn,
                orphaned,
                now_dt,
                now,
                expired_error=f"Exceeded maximum retry window ({int(self.retry_window_seconds)}s) after orphaned processing recovery",
            )
            conn.commit()
            return requeued

    def record_completed(
        self,
        event_id: int,
        reply_task_id: str | None = None,
        reply_message: str | None = None,
        *,
        worker_id: str | None = None,
    ) -> bool:
        """Mark event as completed with optional reply audit trail."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            if worker_id is None:
                cursor = conn.execute(
                    """
                    UPDATE a2a_inbox_events
                    SET status = 'COMPLETED',
                        reply_task_id = ?,
                        reply_message = ?,
                        next_retry_at = NULL,
                        processing_owner = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (reply_task_id, reply_message, now, event_id),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE a2a_inbox_events
                    SET status = 'COMPLETED',
                        reply_task_id = ?,
                        reply_message = ?,
                        next_retry_at = NULL,
                        processing_owner = NULL,
                        updated_at = ?
                    WHERE id = ? AND status = 'PROCESSING' AND processing_owner = ?
                    """,
                    (reply_task_id, reply_message, now, event_id, worker_id),
                )
            conn.commit()
            return cursor.rowcount > 0

    def record_rate_limited(
        self,
        event_id: int,
        retry_after_seconds: float,
        *,
        reply_task_id: str | None = None,
        reply_message: str | None = None,
        worker_id: str | None = None,
    ) -> bool:
        """Defer a 429 reply using max(Retry-After, 2^attempts) capped at 60s within retry_window_seconds."""
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self._get_conn() as conn:
            if worker_id is None:
                row = conn.execute(
                    "SELECT attempts, first_failed_at FROM a2a_inbox_events WHERE id = ? AND status = 'PROCESSING'",
                    (event_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT attempts, first_failed_at FROM a2a_inbox_events WHERE id = ? AND status = 'PROCESSING' AND processing_owner = ?",
                    (event_id, worker_id),
                ).fetchone()
            if row is None:
                return False

            attempts = max(1, int(row["attempts"] or 1))
            exp_delay = float(2 ** min(attempts, 6))
            delay = min(self.max_backoff_seconds, max(0.5, float(retry_after_seconds), exp_delay))
            next_retry = datetime.fromtimestamp(now_dt.timestamp() + delay, tz=timezone.utc).isoformat()

            if self._is_retry_deadline_expired(row["first_failed_at"], now_dt):
                next_status = "FAILED"
                target_retry_at = None
                err_msg = f"Rate limited; retry window ({int(self.retry_window_seconds)}s) exceeded"
            else:
                next_status = "ACKNOWLEDGED"
                target_retry_at = next_retry
                err_msg = f"Rate limited; deferred {delay:.2f}s"

            if worker_id is None:
                cursor = conn.execute(
                    """
                    UPDATE a2a_inbox_events
                    SET status = ?,
                        processing_owner = NULL,
                        next_retry_at = ?,
                        first_failed_at = COALESCE(first_failed_at, ?),
                        reply_task_id = COALESCE(?, reply_task_id),
                        reply_message = COALESCE(?, reply_message),
                        error = ?,
                        updated_at = ?
                    WHERE id = ? AND status = 'PROCESSING'
                    """,
                    (
                        next_status,
                        target_retry_at,
                        now,
                        reply_task_id,
                        reply_message,
                        err_msg,
                        now,
                        event_id,
                    ),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE a2a_inbox_events
                    SET status = ?,
                        processing_owner = NULL,
                        next_retry_at = ?,
                        first_failed_at = COALESCE(first_failed_at, ?),
                        reply_task_id = COALESCE(?, reply_task_id),
                        reply_message = COALESCE(?, reply_message),
                        error = ?,
                        updated_at = ?
                    WHERE id = ? AND status = 'PROCESSING' AND processing_owner = ?
                    """,
                    (
                        next_status,
                        target_retry_at,
                        now,
                        reply_task_id,
                        reply_message,
                        err_msg,
                        now,
                        event_id,
                        worker_id,
                    ),
                )
            conn.commit()
            return cursor.rowcount > 0

    def record_suppressed(
        self,
        event_id: int,
        reason: str = "anti-echo",
        *,
        worker_id: str | None = None,
    ) -> bool:
        """Mark event as suppressed (no reciprocal reply sent)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            if worker_id is None:
                cursor = conn.execute(
                    """
                    UPDATE a2a_inbox_events
                    SET status = 'SUPPRESSED',
                        next_retry_at = NULL,
                        processing_owner = NULL,
                        error = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (f"Suppressed: {reason}", now, event_id),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE a2a_inbox_events
                    SET status = 'SUPPRESSED',
                        next_retry_at = NULL,
                        processing_owner = NULL,
                        error = ?,
                        updated_at = ?
                    WHERE id = ? AND status = 'PROCESSING' AND processing_owner = ?
                    """,
                    (f"Suppressed: {reason}", now, event_id, worker_id),
                )
            conn.commit()
            return cursor.rowcount > 0

    def record_failed(
        self,
        event_id: int,
        error_message: str,
        *,
        worker_id: str | None = None,
        backoff_seconds: float | None = None,
    ) -> bool:
        """Record failure with capped exponential backoff (60s), marking FAILED after retry_window_seconds."""
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self._get_conn() as conn:
            if worker_id is None:
                row = conn.execute(
                    "SELECT attempts, first_failed_at FROM a2a_inbox_events WHERE id = ?",
                    (event_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT attempts, first_failed_at FROM a2a_inbox_events WHERE id = ? AND status = 'PROCESSING' AND processing_owner = ?",
                    (event_id, worker_id),
                ).fetchone()
            if row is None:
                return False

            attempts = max(1, int(row["attempts"] or 1))
            if self._is_retry_deadline_expired(row["first_failed_at"], now_dt):
                next_status = "FAILED"
                next_retry_at = None
            else:
                next_status = "ACKNOWLEDGED"
                raw_delay = (
                    max(0.0, float(backoff_seconds))
                    if backoff_seconds is not None
                    else float(2 ** min(attempts, 6))
                )
                delay = min(self.max_backoff_seconds, raw_delay)
                next_retry_at = (
                    datetime.fromtimestamp(now_dt.timestamp() + delay, tz=timezone.utc).isoformat()
                    if delay > 0
                    else None
                )

            if worker_id is None:
                cursor = conn.execute(
                    """
                    UPDATE a2a_inbox_events
                    SET error = ?,
                        next_retry_at = ?,
                        first_failed_at = COALESCE(first_failed_at, ?),
                        processing_owner = NULL,
                        status = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (error_message[:500], next_retry_at, now, next_status, now, event_id),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE a2a_inbox_events
                    SET error = ?,
                        next_retry_at = ?,
                        first_failed_at = COALESCE(first_failed_at, ?),
                        processing_owner = NULL,
                        status = ?,
                        updated_at = ?
                    WHERE id = ? AND status = 'PROCESSING' AND processing_owner = ?
                    """,
                    (error_message[:500], next_retry_at, now, next_status, now, event_id, worker_id),
                )
            conn.commit()
            return cursor.rowcount > 0

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
                if row and row["status"] != "SENT":
                    conn.execute(
                        "UPDATE a2a_outbound_tasks SET task_id = ?, message = ? WHERE idempotency_key = ? AND status != 'SENT'",
                        (task_id, message, idempotency_key),
                    )
                    conn.commit()
                    return True
                return False

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

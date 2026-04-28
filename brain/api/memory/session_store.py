"""SQLite-backed session store with inflight guard and dedup."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, dataclass
from typing import Any
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from time import monotonic

from config import get_settings
from infra.datetime_utils import normalize_iso_timestamp, utc_now_iso
from personas.personas import normalize_persona_id


def _decode_metadata(raw: str | None) -> dict[str, Any] | None:
    """Decode a stored metadata JSON blob; return None if empty or invalid."""
    if raw is None or raw == "":
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(value, dict):
        return value
    return None


def _validate_persona_match(existing_raw: str | None, expected: str) -> None:
    """Raise if a session's persona doesn't match the expected one."""
    existing = normalize_persona_id(str(existing_raw or "default"))
    if existing != normalize_persona_id(expected):
        raise ValueError("session_id 已綁定其他 persona")


@dataclass(slots=True)
class SessionMessage:
    role: str
    content: str
    created_at: str
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class SessionState:
    session_id: str
    persona_id: str
    created_at: str
    updated_at: str
    messages: list[SessionMessage]


class InflightError(RuntimeError):
    """Raised when a session already has an in-flight generation."""


class DuplicateMessageError(RuntimeError):
    """Raised when a duplicate message is submitted within the dedup window."""


_DEDUP_WINDOW_SECONDS = 5.0



class SessionStore:
    """Persist chat sessions in SQLite so they survive process restarts.

    Provides three concurrency guards for WebSocket sessions:

    * **Inflight guard** — ``acquire_inflight`` / ``release_inflight`` ensure
      only one generation runs per session at a time.
    * **Dedup window** — ``check_dedup`` rejects identical messages submitted
      within a short time window.
    * **Interrupt-safe reset** — ``interrupt_session`` releases the inflight
      lock and clears pending state so the session can accept new input.
    """

    def __init__(self, db_path: str | None = None) -> None:
        cfg = get_settings()
        self._db_path = Path(db_path or cfg.session_db_resolved_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

        # Inflight guard: per-session lock (session_id → threading.Lock)
        self._inflight_locks: dict[str, threading.Lock] = {}
        self._inflight_meta_lock = Lock()

        # Dedup window: session_id → (message_hash, monotonic_timestamp)
        self._dedup_cache: dict[str, tuple[int, float]] = {}
        self._dedup_lock = Lock()

    def get_or_create_session(
        self,
        session_id: str,
        persona_id: str = "default",
    ) -> SessionState:
        with self._lock:
            self._prune_expired_sessions_locked()
            now = utc_now_iso()
            persona_key = normalize_persona_id(persona_id)
            with self._connect() as conn:
                self._ensure_session_persona_locked(conn, session_id, persona_key, now)
                conn.commit()
                return self._load_session_locked(conn, session_id)

    def append_message(
        self,
        session_id: str,
        persona_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[SessionState, int]:
        cfg = get_settings()
        now = utc_now_iso()
        max_messages = max(cfg.max_session_rounds * 2, 20)
        persona_key = normalize_persona_id(persona_id)
        metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

        with self._lock:
            self._prune_expired_sessions_locked()
            with self._connect() as conn:
                self._ensure_session_persona_locked(conn, session_id, persona_key, now)
                cursor = conn.execute(
                    "INSERT INTO messages(session_id, role, content, created_at, metadata) VALUES (?, ?, ?, ?, ?)",
                    (session_id, role, content, now, metadata_json),
                )
                message_id = int(cursor.lastrowid or 0)

                # Prune oldest messages beyond the limit
                overflow_ids = [
                    row[0] for row in conn.execute(
                        "SELECT id FROM messages WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT -1 OFFSET ?",
                        (session_id, max_messages),
                    ).fetchall()
                ]
                if overflow_ids:
                    placeholders = ",".join("?" for _ in overflow_ids)
                    conn.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", overflow_ids)
                conn.commit()
                return self._load_session_locked(conn, session_id), message_id

    def update_message_metadata(self, message_id: int, metadata: dict[str, Any]) -> None:
        """Merge ``metadata`` into the existing message metadata."""
        if message_id <= 0 or not metadata:
            return
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT metadata FROM messages WHERE id = ?", (message_id,),
                ).fetchone()
                if row is None:
                    return
                existing = json.loads(row[0]) if row[0] else {}
                existing.update(metadata)
                conn.execute(
                    "UPDATE messages SET metadata = ? WHERE id = ?",
                    (json.dumps(existing, ensure_ascii=False), message_id),
                )
                conn.commit()

    def list_messages(
        self,
        session_id: str,
        persona_id: str | None = None,
    ) -> list[dict[str, str]]:
        with self._lock:
            self._prune_expired_sessions_locked()
            with self._connect() as conn:
                # Validate session exists and persona matches, but don't create
                row = conn.execute(
                    "SELECT persona_id FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if row is None:
                    return []
                if persona_id is not None:
                    _validate_persona_match(row[0], persona_id)
                rows = conn.execute(
                    """
                    SELECT role, content, created_at, metadata
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY created_at ASC, id ASC
                    """,
                    (session_id,),
                ).fetchall()
                return [
                    asdict(
                        SessionMessage(
                            role=row[0],
                            content=row[1],
                            created_at=normalize_iso_timestamp(row[2]),
                            metadata=_decode_metadata(row[3]),
                        )
                    )
                    for row in rows
                ]

    def get_session_updated_at(
        self,
        session_id: str,
        persona_id: str | None = None,
    ) -> str | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT persona_id, updated_at
                    FROM sessions
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
                if row is None:
                    return None
                if persona_id is not None:
                    _validate_persona_match(row[0], persona_id)
                return normalize_iso_timestamp(row[1])

    def list_sessions(self, persona_id: str | None = None) -> list[dict[str, object]]:
        """List sessions that have at least one message."""
        with self._lock:
            with self._connect() as conn:
                base_sql = """
                    SELECT
                        s.session_id,
                        s.persona_id,
                        s.created_at,
                        s.updated_at,
                        (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.session_id) AS message_count,
                        (SELECT m.content FROM messages m WHERE m.session_id = s.session_id ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_message_preview
                    FROM sessions s
                    WHERE EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.session_id)
                """
                params: tuple[str, ...] = ()
                if persona_id:
                    base_sql += " AND s.persona_id = ?"
                    params = (normalize_persona_id(persona_id),)
                base_sql += " ORDER BY s.updated_at DESC"

                return [
                    {
                        "session_id": row[0],
                        "persona_id": row[1],
                        "created_at": normalize_iso_timestamp(row[2]),
                        "updated_at": normalize_iso_timestamp(row[3]),
                        "message_count": row[4],
                        "last_message_preview": (row[5] or "")[:120],
                    }
                    for row in conn.execute(base_sql, params).fetchall()
                ]

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its messages (CASCADE)."""
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM sessions WHERE session_id = ?",
                    (session_id,),
                )
                conn.commit()
                deleted = cursor.rowcount > 0
        if deleted:
            self._cleanup_session_memory(session_id)
        return deleted

    # ------------------------------------------------------------------
    # Inflight guard
    # ------------------------------------------------------------------

    def acquire_inflight(self, session_id: str) -> None:
        """Mark a session as having an active generation.

        Raises ``InflightError`` if the session already has one running.
        This is non-blocking — it fails immediately rather than waiting.
        """
        lock = self._get_inflight_lock(session_id)
        acquired = lock.acquire(blocking=False)
        if not acquired:
            raise InflightError(
                f"session {session_id} 已有進行中的回應，請稍候"
            )

    def release_inflight(self, session_id: str) -> None:
        """Release the inflight lock for a session.

        Safe to call even if not currently held (e.g. after interrupt).
        """
        lock = self._get_inflight_lock(session_id)
        try:
            lock.release()
        except RuntimeError:
            pass  # already released

    def _get_inflight_lock(self, session_id: str) -> threading.Lock:
        with self._inflight_meta_lock:
            if session_id not in self._inflight_locks:
                self._inflight_locks[session_id] = threading.Lock()
            return self._inflight_locks[session_id]

    # ------------------------------------------------------------------
    # Dedup window
    # ------------------------------------------------------------------

    def check_dedup(self, session_id: str, text: str) -> None:
        """Reject duplicate messages within the dedup window.

        Raises ``DuplicateMessageError`` if the same text was submitted
        to this session within the last ``_DEDUP_WINDOW_SECONDS`` seconds.
        """
        msg_hash = hash(text)
        now = monotonic()

        with self._dedup_lock:
            prev = self._dedup_cache.get(session_id)
            if prev is not None:
                prev_hash, prev_time = prev
                if prev_hash == msg_hash and (now - prev_time) < _DEDUP_WINDOW_SECONDS:
                    raise DuplicateMessageError(
                        f"session {session_id} 重複訊息已忽略"
                    )
            self._dedup_cache[session_id] = (msg_hash, now)

    # ------------------------------------------------------------------
    # Interrupt-safe reset
    # ------------------------------------------------------------------

    def interrupt_session(self, session_id: str) -> None:
        """Reset a session to accept new input after an interrupt.

        Releases the inflight lock and clears the dedup cache entry so
        the interrupted text can be resubmitted immediately.
        """
        self.release_inflight(session_id)
        with self._dedup_lock:
            self._dedup_cache.pop(session_id, None)

    def set_recall_disabled(self, session_id: str, disabled: bool) -> None:
        """Persist the per-session recall toggle."""
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE sessions SET recall_disabled = ? WHERE session_id = ?",
                    (1 if disabled else 0, session_id),
                )
                conn.commit()

    def is_recall_disabled(self, session_id: str) -> bool:
        """Check whether auto recall is disabled for *session_id*."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT recall_disabled FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                return bool(row and row[0])

    def _cleanup_session_memory(self, session_id: str) -> None:
        """Remove in-memory state for a deleted/expired session."""
        with self._inflight_meta_lock:
            self._inflight_locks.pop(session_id, None)
        with self._dedup_lock:
            self._dedup_cache.pop(session_id, None)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    persona_id TEXT NOT NULL DEFAULT 'default',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if "persona_id" not in columns:
                conn.execute(
                    "ALTER TABLE sessions ADD COLUMN persona_id TEXT NOT NULL DEFAULT 'default'"
                )
            if "recall_disabled" not in columns:
                conn.execute(
                    "ALTER TABLE sessions ADD COLUMN recall_disabled INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            message_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "metadata" not in message_columns:
                conn.execute("ALTER TABLE messages ADD COLUMN metadata TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_session_created_at ON messages(session_id, created_at, id)"
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _load_session_locked(self, conn: sqlite3.Connection, session_id: str) -> SessionState:
        """Load a session that is known to exist (called after _ensure_session_persona_locked)."""
        row = conn.execute(
            "SELECT session_id, persona_id, created_at, updated_at FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        messages = [
            SessionMessage(
                role=msg[0],
                content=msg[1],
                created_at=msg[2],
                metadata=_decode_metadata(msg[3]),
            )
            for msg in conn.execute(
                "SELECT role, content, created_at, metadata FROM messages WHERE session_id = ? ORDER BY created_at ASC, id ASC",
                (session_id,),
            ).fetchall()
        ]
        return SessionState(
            session_id=row[0],
            persona_id=normalize_persona_id(str(row[1] or "default")),
            created_at=normalize_iso_timestamp(row[2]),
            updated_at=normalize_iso_timestamp(row[3]),
            messages=messages,
        )

    def _ensure_session_persona_locked(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        persona_id: str,
        now: str | None = None,
    ) -> None:
        timestamp = now or utc_now_iso()
        row = conn.execute(
            "SELECT persona_id FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO sessions(session_id, persona_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, persona_id, timestamp, timestamp),
            )
            return

        _validate_persona_match(row[0], persona_id)
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
            (timestamp, session_id),
        )

    def _prune_expired_sessions_locked(self) -> None:
        cfg = get_settings()
        expiry = datetime.now(UTC) - timedelta(minutes=cfg.max_session_ttl_minutes)
        with self._connect() as conn:
            # Collect session IDs to prune before deleting
            expired_ids = [
                row[0] for row in conn.execute(
                    "SELECT session_id FROM sessions WHERE updated_at < ?",
                    (expiry.isoformat(timespec="seconds"),),
                ).fetchall()
            ]
            empty_cutoff = (datetime.now(UTC) - timedelta(minutes=5)).isoformat(timespec="seconds")
            empty_ids = [
                row[0] for row in conn.execute(
                    """
                    SELECT session_id FROM sessions
                    WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.session_id = sessions.session_id)
                      AND updated_at < ?
                    """,
                    (empty_cutoff,),
                ).fetchall()
            ]
            pruned_ids = set(expired_ids) | set(empty_ids)
            if expired_ids:
                conn.execute(
                    "DELETE FROM sessions WHERE updated_at < ?",
                    (expiry.isoformat(timespec="seconds"),),
                )
            if empty_ids:
                conn.execute(
                    """
                    DELETE FROM sessions
                    WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.session_id = sessions.session_id)
                      AND updated_at < ?
                    """,
                    (empty_cutoff,),
                )
            conn.commit()
        # Clean up in-memory state outside the DB lock
        for sid in pruned_ids:
            self._cleanup_session_memory(sid)

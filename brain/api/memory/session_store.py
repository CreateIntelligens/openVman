"""SQLite-backed session store."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

from config import get_settings
from personas.personas import normalize_persona_id


@dataclass(slots=True)
class SessionMessage:
    role: str
    content: str
    created_at: str


@dataclass(slots=True)
class SessionState:
    session_id: str
    persona_id: str
    created_at: str
    updated_at: str
    messages: list[SessionMessage]


class SessionStore:
    """Persist chat sessions in SQLite so they survive process restarts."""

    def __init__(self, db_path: str | None = None) -> None:
        cfg = get_settings()
        self._db_path = Path(db_path or cfg.session_db_resolved_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

    def get_or_create_session(
        self,
        session_id: str,
        persona_id: str = "default",
    ) -> SessionState:
        with self._lock:
            self._prune_expired_sessions_locked()
            now = datetime.now().isoformat(timespec="seconds")
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
    ) -> SessionState:
        cfg = get_settings()
        now = datetime.now().isoformat(timespec="seconds")
        max_messages = max(cfg.max_session_rounds * 2, 20)
        persona_key = normalize_persona_id(persona_id)

        with self._lock:
            self._prune_expired_sessions_locked()
            with self._connect() as conn:
                self._ensure_session_persona_locked(conn, session_id, persona_key, now)
                conn.execute(
                    """
                    INSERT INTO messages(session_id, role, content, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (session_id, role, content, now),
                )

                message_ids = [
                    row[0]
                    for row in conn.execute(
                        """
                        SELECT id
                        FROM messages
                        WHERE session_id = ?
                        ORDER BY created_at DESC, id DESC
                        LIMIT -1 OFFSET ?
                        """,
                        (session_id, max_messages),
                    ).fetchall()
                ]
                if message_ids:
                    placeholders = ",".join("?" for _ in message_ids)
                    conn.execute(
                        f"DELETE FROM messages WHERE id IN ({placeholders})",
                        message_ids,
                    )
                conn.commit()
                return self._load_session_locked(conn, session_id)

    def list_messages(
        self,
        session_id: str,
        persona_id: str | None = None,
    ) -> list[dict[str, str]]:
        with self._lock:
            self._prune_expired_sessions_locked()
            with self._connect() as conn:
                if persona_id is None:
                    self._ensure_session_exists_locked(conn, session_id)
                else:
                    self._ensure_session_persona_locked(
                        conn,
                        session_id,
                        normalize_persona_id(persona_id),
                    )
                rows = conn.execute(
                    """
                    SELECT role, content, created_at
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
                            created_at=row[2],
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
                    existing_persona = normalize_persona_id(str(row[0] or "default"))
                    if existing_persona != normalize_persona_id(persona_id):
                        raise ValueError("session_id 已綁定其他 persona")
                return str(row[1] or "")

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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_session_created_at ON messages(session_id, created_at, id)"
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _load_session_locked(self, conn: sqlite3.Connection, session_id: str) -> SessionState:
        row = conn.execute(
            """
            SELECT session_id, persona_id, created_at, updated_at
            FROM sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            self._ensure_session_exists_locked(conn, session_id)
            row = conn.execute(
                """
                SELECT session_id, persona_id, created_at, updated_at
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

        messages = [
            SessionMessage(role=msg[0], content=msg[1], created_at=msg[2])
            for msg in conn.execute(
                """
                SELECT role, content, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
        ]
        return SessionState(
            session_id=row[0],
            persona_id=normalize_persona_id(str(row[1] or "default")),
            created_at=row[2],
            updated_at=row[3],
            messages=messages,
        )

    def _ensure_session_exists_locked(self, conn: sqlite3.Connection, session_id: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO sessions(session_id, persona_id, created_at, updated_at)
            VALUES (?, 'default', ?, ?)
            ON CONFLICT(session_id) DO NOTHING
            """,
            (session_id, now, now),
        )
        conn.commit()

    def _ensure_session_persona_locked(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        persona_id: str,
        now: str | None = None,
    ) -> None:
        timestamp = now or datetime.now().isoformat(timespec="seconds")
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

        existing_persona = normalize_persona_id(str(row[0] or "default"))
        if existing_persona != persona_id:
            raise ValueError("session_id 已綁定其他 persona")
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
            (timestamp, session_id),
        )

    def _prune_expired_sessions_locked(self) -> None:
        cfg = get_settings()
        expiry = datetime.now() - timedelta(minutes=cfg.max_session_ttl_minutes)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE updated_at < ?",
                (expiry.isoformat(timespec="seconds"),),
            )
            conn.commit()

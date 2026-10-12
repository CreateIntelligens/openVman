"""Read access to the append-only authentication audit log."""

from __future__ import annotations

import sqlite3

from .database import AuthDatabase
from .models import AuthAuditEventRecord


def _audit_from_row(row: sqlite3.Row) -> AuthAuditEventRecord:
    return AuthAuditEventRecord(
        id=row["id"],
        action=row["action"],
        actor_user_id=row["actor_user_id"],
        target_user_id=row["target_user_id"],
        created_at=row["created_at"],
        metadata_json=row["metadata_json"],
    )


class AuthAuditRepository:
    """Read append-only authentication audit events for tests and operators."""

    def __init__(self, database: AuthDatabase) -> None:
        self.database = database

    def list(self) -> tuple[AuthAuditEventRecord, ...]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM auth_audit_events
                ORDER BY created_at, id
                """
            ).fetchall()
        return tuple(_audit_from_row(row) for row in rows)

"""Aggregate record of which websites call the API with which credential."""

from __future__ import annotations

from dataclasses import dataclass

from ._repository_base import now_iso
from .database import AuthDatabase

# 網域與路徑都是請求端給的字串，存之前截短，不讓一個請求塞爆一列。
_MAX_ORIGIN_LENGTH = 255
_MAX_PATH_LENGTH = 255


@dataclass(frozen=True, slots=True)
class RequestOriginRecord:
    origin: str
    principal_type: str
    principal_id: str
    user_id: str | None
    first_seen_at: str
    last_seen_at: str
    last_path: str
    request_count: int


class RequestOriginRepository:
    def __init__(self, database: AuthDatabase) -> None:
        self.database = database

    def record(
        self,
        *,
        origin: str,
        principal_type: str,
        principal_id: str,
        user_id: str | None,
        path: str,
    ) -> None:
        seen_at = now_iso()
        with self.database.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO request_origins(
                    origin, principal_type, principal_id, user_id,
                    first_seen_at, last_seen_at, last_path, request_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(origin, principal_type, principal_id) DO UPDATE SET
                    user_id = COALESCE(excluded.user_id, request_origins.user_id),
                    last_seen_at = excluded.last_seen_at,
                    last_path = excluded.last_path,
                    request_count = request_origins.request_count + 1
                """,
                (
                    origin[:_MAX_ORIGIN_LENGTH],
                    principal_type,
                    principal_id,
                    user_id,
                    seen_at,
                    seen_at,
                    path[:_MAX_PATH_LENGTH],
                ),
            )

    def list_recent(self, limit: int = 200) -> list[RequestOriginRecord]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT origin, principal_type, principal_id, user_id, first_seen_at,
                       last_seen_at, last_path, request_count
                FROM request_origins
                ORDER BY last_seen_at DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [
            RequestOriginRecord(
                origin=row["origin"],
                principal_type=row["principal_type"],
                principal_id=row["principal_id"],
                user_id=row["user_id"],
                first_seen_at=row["first_seen_at"],
                last_seen_at=row["last_seen_at"],
                last_path=row["last_path"],
                request_count=int(row["request_count"]),
            )
            for row in rows
        ]

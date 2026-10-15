"""Ownership registry for projects, avatars, voices, and other resources."""

from __future__ import annotations

import json
import sqlite3

from ._repository_base import now_iso
from .database import AuthDatabase
from .models import ResourceRecord, ResourceType, ResourceVisibility
from .repository_errors import RepositoryError, ResourceConflictError


def _resource_from_row(row: sqlite3.Row) -> ResourceRecord:
    return ResourceRecord(
        resource_type=ResourceType(row["resource_type"]),
        resource_id=row["resource_id"],
        owner_user_id=row["owner_user_id"],
        visibility=ResourceVisibility(row["visibility"]),
        created_at=row["created_at"],
        metadata_json=row["metadata_json"],
        owner_project_id=row["owner_project_id"] if "owner_project_id" in row.keys() else None,
    )


class ResourceRepository:
    def __init__(self, database: AuthDatabase) -> None:
        self.database = database

    def register(
        self,
        *,
        resource_type: ResourceType,
        resource_id: str,
        visibility: ResourceVisibility,
        owner_user_id: str | None,
        metadata: dict[str, object] | None = None,
        owner_project_id: str | None = None,
    ) -> ResourceRecord:
        normalized_id = resource_id.strip()
        if not normalized_id:
            raise ValueError("resource_id must not be empty")
        if visibility is ResourceVisibility.PRIVATE and owner_user_id is None:
            raise ValueError("private resources require an owner")
        if visibility is ResourceVisibility.SYSTEM_PUBLIC and owner_user_id is not None:
            raise ValueError("system-public resources must not have an owner")
        if visibility is ResourceVisibility.PROJECT and owner_user_id is not None:
            raise ValueError("project resources must not have a user owner")

        try:
            with self.database.transaction(write=True) as connection:
                connection.execute(
                    """
                    INSERT INTO resources(
                        resource_type, resource_id, owner_user_id, visibility,
                        created_at, metadata_json, owner_project_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resource_type.value,
                        normalized_id,
                        owner_user_id,
                        visibility.value,
                        now_iso(),
                        json.dumps(
                            metadata or {}, separators=(",", ":"), sort_keys=True
                        ),
                        owner_project_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "resources.resource_type, resources.resource_id" in str(exc):
                raise ResourceConflictError("resource already registered") from exc
            raise

        record = self.get(resource_type, normalized_id)
        if record is None:
            raise RepositoryError("registered resource could not be reloaded")
        return record

    def upsert_system_resource(
        self,
        *,
        resource_type: ResourceType,
        resource_id: str,
        metadata: dict[str, object] | None = None,
    ) -> ResourceRecord:
        normalized_id = resource_id.strip()
        if not normalized_id:
            raise ValueError("resource_id must not be empty")

        with self.database.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO resources(
                    resource_type, resource_id, owner_user_id, visibility,
                    created_at, metadata_json
                ) VALUES (?, ?, NULL, 'system_public', ?, ?)
                ON CONFLICT(resource_type, resource_id) DO UPDATE SET
                    metadata_json = excluded.metadata_json
                """,
                (
                    resource_type.value,
                    normalized_id,
                    now_iso(),
                    json.dumps(
                        metadata or {}, separators=(",", ":"), sort_keys=True
                    ),
                ),
            )
        record = self.get(resource_type, normalized_id)
        if record is None:
            raise RepositoryError("upserted resource could not be reloaded")
        return record

    def update_metadata(
        self,
        resource_type: ResourceType,
        resource_id: str,
        metadata: dict[str, object],
    ) -> ResourceRecord:
        normalized_id = resource_id.strip()
        with self.database.transaction(write=True) as connection:
            connection.execute(
                """
                UPDATE resources
                SET metadata_json = ?
                WHERE resource_type = ? AND resource_id = ?
                """,
                (
                    json.dumps(
                        metadata or {}, separators=(",", ":"), sort_keys=True
                    ),
                    resource_type.value,
                    normalized_id,
                ),
            )
        record = self.get(resource_type, normalized_id)
        if record is None:
            raise RepositoryError("updated resource could not be reloaded")
        return record


    def get(
        self,
        resource_type: ResourceType,
        resource_id: str,
    ) -> ResourceRecord | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM resources
                WHERE resource_type = ? AND resource_id = ?
                """,
                (resource_type.value, resource_id),
            ).fetchone()
        return _resource_from_row(row) if row is not None else None

    def list_owned(
        self,
        owner_user_id: str,
        *,
        resource_type: ResourceType | None = None,
    ) -> list[ResourceRecord]:
        query = "SELECT * FROM resources WHERE owner_user_id = ?"
        params: list[str] = [owner_user_id]
        if resource_type is not None:
            query += " AND resource_type = ?"
            params.append(resource_type.value)
        query += " ORDER BY resource_type, resource_id"
        with self.database.transaction() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_resource_from_row(row) for row in rows]

    def list_by_type(
        self,
        resource_type: ResourceType,
    ) -> list[ResourceRecord]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM resources
                WHERE resource_type = ?
                ORDER BY resource_id
                """,
                (resource_type.value,),
            ).fetchall()
        return [_resource_from_row(row) for row in rows]

    def list_accessible(
        self,
        user_id: str,
        *,
        resource_type: ResourceType,
    ) -> list[ResourceRecord]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT resources.*
                FROM resources
                LEFT JOIN resource_grants
                    ON resource_grants.resource_type = resources.resource_type
                   AND resource_grants.resource_id = resources.resource_id
                   AND resource_grants.grantee_user_id = ?
                WHERE resources.resource_type = ?
                  AND (
                      resources.owner_user_id = ?
                      OR resource_grants.grantee_user_id IS NOT NULL
                  )
                ORDER BY resources.resource_id
                """,
                (user_id, resource_type.value, user_id),
            ).fetchall()
        return [_resource_from_row(row) for row in rows]

    def has_grant(
        self,
        grantee_user_id: str,
        resource_type: ResourceType,
        resource_id: str,
    ) -> bool:
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM resource_grants
                WHERE grantee_user_id = ?
                  AND resource_type = ?
                  AND resource_id = ?
                """,
                (grantee_user_id, resource_type.value, resource_id),
            ).fetchone()
        return row is not None

    def count_private_by_owner(self, owner_user_id: str) -> dict[str, int]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT resource_type, COUNT(*) AS resource_count
                FROM resources
                WHERE owner_user_id = ? AND visibility = 'private'
                GROUP BY resource_type
                ORDER BY resource_type
                """,
                (owner_user_id,),
            ).fetchall()
        return {row["resource_type"]: int(row["resource_count"]) for row in rows}

    def unregister(
        self,
        resource_type: ResourceType,
        resource_id: str,
    ) -> bool:
        with self.database.transaction(write=True) as connection:
            if resource_type is ResourceType.PROJECT:
                connection.execute(
                    """
                    UPDATE resources
                    SET owner_project_id = NULL
                    WHERE owner_project_id = ?
                    """,
                    (resource_id,),
                )
            deleted = connection.execute(
                """
                DELETE FROM resources
                WHERE resource_type = ? AND resource_id = ?
                """,
                (resource_type.value, resource_id),
            ).rowcount
        return deleted > 0

    def list_by_owner_project(
        self,
        owner_project_id: str,
        *,
        resource_type: ResourceType | None = None,
    ) -> list[ResourceRecord]:
        query = "SELECT * FROM resources WHERE owner_project_id = ? AND visibility = 'project'"
        params: list[str] = [owner_project_id]
        if resource_type is not None:
            query += " AND resource_type = ?"
            params.append(resource_type.value)
        query += " ORDER BY resource_type, resource_id"
        with self.database.transaction() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_resource_from_row(row) for row in rows]

    def list_orphans(
        self,
        *,
        resource_type: ResourceType | None = None,
    ) -> list[ResourceRecord]:
        query = "SELECT * FROM resources WHERE visibility = 'project' AND owner_project_id IS NULL"
        params: list[str] = []
        if resource_type is not None:
            query += " AND resource_type = ?"
            params.append(resource_type.value)
        query += " ORDER BY resource_type, resource_id"
        with self.database.transaction() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_resource_from_row(row) for row in rows]

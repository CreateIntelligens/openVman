"""Persistence and querying for ROOT-assigned project resources."""

from __future__ import annotations

import sqlite3

from ._account_records import _append_auth_audit
from ._repository_base import now_iso
from .database import AuthDatabase
from .models import ProjectResourceAssignmentRecord, ResourceType


def _assignment_from_row(row: sqlite3.Row) -> ProjectResourceAssignmentRecord:
    return ProjectResourceAssignmentRecord(
        project_id=row["project_id"],
        resource_type=ResourceType(row["resource_type"]),
        resource_id=row["resource_id"],
        assigned_by=row["assigned_by"],
        assigned_at=row["assigned_at"],
    )


class ProjectResourceAssignmentRepository:
    def __init__(self, database: AuthDatabase) -> None:
        self.database = database

    def assign(
        self,
        *,
        project_id: str,
        resource_type: ResourceType,
        resource_id: str,
        assigned_by: str | None,
    ) -> ProjectResourceAssignmentRecord:
        now = now_iso()
        with self.database.transaction(write=True) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO project_resource_assignments(
                    project_id, resource_type, resource_id, assigned_by, assigned_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    resource_type.value,
                    resource_id,
                    assigned_by,
                    now,
                ),
            )
            if cursor.rowcount > 0:
                _append_auth_audit(
                    connection,
                    action="project_resource_assigned",
                    actor_user_id=assigned_by,
                    target_user_id=None,
                    metadata={
                        "project_id": project_id,
                        "resource_type": resource_type.value,
                        "resource_id": resource_id,
                    },
                    now=now,
                )
            row = connection.execute(
                """
                SELECT * FROM project_resource_assignments
                WHERE project_id = ? AND resource_type = ? AND resource_id = ?
                """,
                (project_id, resource_type.value, resource_id),
            ).fetchone()
        assert row is not None
        return _assignment_from_row(row)

    def unassign(
        self,
        *,
        project_id: str,
        resource_type: ResourceType,
        resource_id: str,
        unassigned_by: str | None = None,
    ) -> bool:
        now = now_iso()
        with self.database.transaction(write=True) as connection:
            deleted = connection.execute(
                """
                DELETE FROM project_resource_assignments
                WHERE project_id = ? AND resource_type = ? AND resource_id = ?
                """,
                (project_id, resource_type.value, resource_id),
            ).rowcount
            if deleted > 0:
                _append_auth_audit(
                    connection,
                    action="project_resource_unassigned",
                    actor_user_id=unassigned_by,
                    target_user_id=None,
                    metadata={
                        "project_id": project_id,
                        "resource_type": resource_type.value,
                        "resource_id": resource_id,
                    },
                    now=now,
                )
        return deleted > 0

    def list_for_project(
        self,
        project_id: str,
        resource_type: ResourceType | None = None,
    ) -> list[ProjectResourceAssignmentRecord]:
        query = (
            "SELECT * FROM project_resource_assignments WHERE project_id = ?"
        )
        params: list[str] = [project_id]
        if resource_type is not None:
            query += " AND resource_type = ?"
            params.append(resource_type.value)
        query += " ORDER BY resource_type, resource_id"
        with self.database.transaction() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_assignment_from_row(row) for row in rows]

    def is_assigned(
        self,
        project_id: str,
        resource_type: ResourceType,
        resource_id: str,
    ) -> bool:
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM project_resource_assignments
                WHERE project_id = ? AND resource_type = ? AND resource_id = ?
                """,
                (project_id, resource_type.value, resource_id),
            ).fetchone()
        return row is not None

    def list_projects_for_resource(
        self,
        resource_type: ResourceType,
        resource_id: str,
    ) -> list[str]:
        query = (
            "SELECT project_id FROM project_resource_assignments "
            "WHERE resource_type = ? AND resource_id = ?"
        )
        with self.database.transaction() as connection:
            rows = connection.execute(
                query, (resource_type.value, resource_id)
            ).fetchall()
        return [row[0] for row in rows]

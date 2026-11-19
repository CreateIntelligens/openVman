"""Protect deployed account grants through the vendor-access schema migration."""

from __future__ import annotations

from app.auth.database import AuthDatabase
from app.auth.models import AccountRole, ResourceType
from app.auth.runtime import build_auth_runtime
from app.config import TTSRouterConfig


def test_vendor_access_migration_preserves_legacy_write_and_read_grants(tmp_path):
    db_path = tmp_path / "auth.db"
    runtime = build_auth_runtime(
        TTSRouterConfig(
            _env_file=None, env="dev",
            session_jwt_secret="test-only-vendor-migration-secret",
            auth_database_path=str(db_path),
        )
    )
    root = runtime.users.create_root(username="ai360", password_hash="unused")
    admin = runtime.users.create(
        username="operator", password_hash="unused",
        role=AccountRole.ADMIN, created_by=root.id,
    )
    grants = [
        (ResourceType.PROJECT, "p1"),
        (ResourceType.AVATAR_CHARACTER, "a1"),
        (ResourceType.CUSTOM_VOICE, "v1"),
    ]
    for resource_type, resource_id in grants:
        runtime.resources.upsert_system_resource(
            resource_type=resource_type, resource_id=resource_id,
        )
    defaults = ("p1", "a1", "indextts", "v1")
    writer = runtime.users.create(
        username="writer", password_hash="unused", role=AccountRole.USER, created_by=root.id,
        admin_portal_access=True, grants=grants, defaults=defaults,
    )
    reader = runtime.users.create(
        username="reader", password_hash="unused", role=AccountRole.USER, created_by=root.id,
        grants=grants, defaults=defaults,
    )
    legacy_columns = (
        "grantee_user_id, resource_type, resource_id, granted_by, created_at"
    )
    legacy_query = f"SELECT {legacy_columns} FROM resource_grants ORDER BY 1, 2, 3"
    database = AuthDatabase(runtime.database.path)

    with database.transaction(write=True) as connection:
        # Reconstruct the production v27 schema before seeding the migration run.
        for table, columns in (
            ("users", ("account_management_access", "vendor_name")),
            ("resources", ("vendor_name",)),
            ("resource_grants", ("edit_knowledge", "edit_settings", "project_writes_explicit")),
        ):
            existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            for column in columns:
                if column in existing:
                    connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        connection.execute("DELETE FROM schema_migrations WHERE version = 28")
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 27
        before = [tuple(row) for row in connection.execute(legacy_query)]

    database.initialize()
    with database.transaction(write=True) as connection:
        migrated = {
            row["grantee_user_id"]: (bool(row["edit_knowledge"]), bool(row["edit_settings"]))
            for row in connection.execute(
                "SELECT * FROM resource_grants WHERE resource_type = 'project'",
            )
        }
        assert migrated == {writer.id: (True, True), reader.id: (False, False)}
        assert list(connection.execute("PRAGMA foreign_key_check")) == []
        assert [tuple(row) for row in connection.execute(legacy_query)] == before
        assert not connection.execute(
            "SELECT 1 FROM users WHERE account_management_access != 0 OR vendor_name IS NOT NULL",
        ).fetchone()
        assert not connection.execute(
            "SELECT 1 FROM resources WHERE vendor_name IS NOT NULL",
        ).fetchone()

        # A second restart must not overwrite stage-1 permission or vendor changes.
        connection.execute(
            "UPDATE users SET account_management_access = 1 WHERE id = ?", (admin.id,),
        )
        connection.execute(
            "UPDATE resources SET vendor_name = '甲商' WHERE resource_id = 'p1'",
        )
        connection.execute(
            "UPDATE resource_grants SET edit_settings = 0 WHERE grantee_user_id = ? "
            "AND resource_type = 'project'",
            (writer.id,),
        )

    database.initialize()
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 28",
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT account_management_access FROM users WHERE id = ?", (admin.id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT vendor_name FROM resources WHERE resource_id = 'p1'",
        ).fetchone()[0] == "甲商"
        assert tuple(connection.execute(
            "SELECT edit_knowledge, edit_settings FROM resource_grants "
            "WHERE grantee_user_id = ? AND resource_type = 'project'",
            (writer.id,),
        ).fetchone()) == (1, 0)
        assert [tuple(row) for row in connection.execute(legacy_query)] == before

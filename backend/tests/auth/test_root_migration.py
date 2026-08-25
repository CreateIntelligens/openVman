"""ROOT migration regressions against the previous two-role schema."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.auth.database import _MIGRATIONS, AuthDatabase


def _create_v3_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                details_json TEXT NOT NULL
            )
            """
        )
        for version, name, statements in _MIGRATIONS:
            for index, statement in enumerate(statements):
                if version == 3:
                    columns = {
                        row[1]
                        for row in connection.execute(
                            "PRAGMA table_info(account_defaults)"
                        ).fetchall()
                    }
                    if index == 0 and "mascot_id" in columns:
                        continue
                    if index == 1 and "background_id" in columns:
                        continue
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, details_json) VALUES (?, ?)",
                (version, json.dumps({"name": name})),
            )
        connection.commit()
    finally:
        connection.close()


def _seed_v3_account_graph(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO users(
                id, username, username_normalized, password_hash, role,
                disabled, token_version, created_at, updated_at, created_by,
                account_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "usr_creator",
                "Creator",
                "creator",
                "creator-hash",
                "admin",
                0,
                2,
                "2025-01-01T00:00:00+00:00",
                "2025-01-02T00:00:00+00:00",
                None,
                "formal",
            ),
        )
        connection.execute(
            """
            INSERT INTO users(
                id, username, username_normalized, password_hash, role,
                disabled, token_version, created_at, updated_at, created_by,
                account_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "usr_ai360",
                "ＡＩ360",
                "ai360",
                "preserved-bcrypt-hash",
                "admin",
                0,
                7,
                "2025-02-01T00:00:00+00:00",
                "2025-02-02T00:00:00+00:00",
                "usr_creator",
                "formal",
            ),
        )
        for resource_type, resource_id, owner_id, visibility in (
            ("project", "granted-project", None, "system_public"),
            ("avatar_character", "granted-character", None, "system_public"),
            ("custom_voice", "granted-voice", None, "system_public"),
            ("project", "owned-project", "usr_ai360", "private"),
        ):
            connection.execute(
                """
                INSERT INTO resources(
                    resource_type, resource_id, owner_user_id, visibility,
                    created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, '{}')
                """,
                (
                    resource_type,
                    resource_id,
                    owner_id,
                    visibility,
                    "2025-02-03T00:00:00+00:00",
                ),
            )
        for resource_type, resource_id in (
            ("project", "granted-project"),
            ("avatar_character", "granted-character"),
            ("custom_voice", "granted-voice"),
        ):
            connection.execute(
                """
                INSERT INTO resource_grants(
                    grantee_user_id, resource_type, resource_id,
                    granted_by, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "usr_ai360",
                    resource_type,
                    resource_id,
                    "usr_creator",
                    "2025-02-04T00:00:00+00:00",
                ),
            )
        connection.execute(
            """
            INSERT INTO account_defaults(
                user_id, project_id, character_id, voice_provider, voice_id,
                mascot_id, background_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "usr_ai360",
                "granted-project",
                "granted-character",
                "indextts",
                "granted-voice",
                "",
                "",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_v3_migration_promotes_ai360_in_place_and_preserves_related_data(
    tmp_path: Path,
):
    path = tmp_path / "accounts.db"
    _create_v3_database(path)
    _seed_v3_account_graph(path)

    database = AuthDatabase(path)
    database.initialize()

    with database.transaction() as connection:
        ai360 = connection.execute(
            "SELECT * FROM users WHERE username_normalized = 'ai360'"
        ).fetchone()
        owned = connection.execute(
            "SELECT * FROM resources WHERE owner_user_id = ?",
            ("usr_ai360",),
        ).fetchall()
        grants = connection.execute(
            """
            SELECT resource_type, resource_id, granted_by, created_at
            FROM resource_grants WHERE grantee_user_id = ?
            ORDER BY resource_type, resource_id
            """,
            ("usr_ai360",),
        ).fetchall()
        defaults = connection.execute(
            "SELECT * FROM account_defaults WHERE user_id = ?",
            ("usr_ai360",),
        ).fetchone()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert dict(ai360) == {
        "id": "usr_ai360",
        "username": "ＡＩ360",
        "username_normalized": "ai360",
        "password_hash": "preserved-bcrypt-hash",
        "role": "root",
        "disabled": 0,
        "token_version": 8,
        "created_at": "2025-02-01T00:00:00+00:00",
        "updated_at": ai360["updated_at"],
        "created_by": "usr_creator",
        "account_type": "formal",
    }
    assert ai360["updated_at"] != "2025-02-02T00:00:00+00:00"
    assert [dict(row) for row in owned] == [
        {
            "resource_type": "project",
            "resource_id": "owned-project",
            "owner_user_id": "usr_ai360",
            "visibility": "private",
            "created_at": "2025-02-03T00:00:00+00:00",
            "metadata_json": "{}",
        }
    ]
    assert {(row["resource_type"], row["resource_id"]) for row in grants} == {
        ("project", "granted-project"),
        ("avatar_character", "granted-character"),
        ("custom_voice", "granted-voice"),
    }
    assert all(row["granted_by"] == "usr_creator" for row in grants)
    assert all(
        row["created_at"] == "2025-02-04T00:00:00+00:00" for row in grants
    )
    assert dict(defaults) == {
        "user_id": "usr_ai360",
        "project_id": "granted-project",
        "character_id": "granted-character",
        "voice_provider": "indextts",
        "voice_id": "granted-voice",
        "mascot_id": "",
        "background_id": "",
    }
    assert violations == []


def test_root_migration_is_rerunnable_and_enforces_single_root(tmp_path: Path):
    path = tmp_path / "accounts.db"
    _create_v3_database(path)
    _seed_v3_account_graph(path)
    database = AuthDatabase(path)
    database.initialize()

    with database.transaction() as connection:
        first = dict(
            connection.execute(
                "SELECT * FROM users WHERE username_normalized = 'ai360'"
            ).fetchone()
        )

    database.initialize()

    with database.transaction(write=True) as connection:
        second = dict(
            connection.execute(
                "SELECT * FROM users WHERE username_normalized = 'ai360'"
            ).fetchone()
        )
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        root_index = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'index' AND name = 'ux_users_single_root'
            """
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO users(
                    id, username, username_normalized, password_hash, role,
                    account_type, disabled, token_version, created_at,
                    updated_at, created_by
                ) VALUES (
                    'usr_second_root', 'ai360-copy', 'ai360-copy', 'hash',
                    'root', 'formal', 0, 0, 'now', 'now', NULL
                )
                """
            )

    assert second == first
    applied = [row["version"] for row in versions]
    # 只驗證遷移不重複、且按序套用；確切版本號會隨新遷移增加。
    assert applied == sorted(set(applied))
    assert applied[:4] == [1, 2, 3, 4]
    assert "UNIQUE INDEX" in root_index["sql"]
    assert "WHERE role = 'root'" in root_index["sql"]


def test_root_migration_fails_closed_on_temporary_ai360(tmp_path: Path):
    path = tmp_path / "accounts.db"
    _create_v3_database(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO users(
                id, username, username_normalized, password_hash, role,
                disabled, token_version, created_at, updated_at, created_by,
                account_type
            ) VALUES (
                'usr_conflict', 'ai360', 'ai360', 'original-hash', 'user',
                0, 4, 'created', 'updated', NULL, 'temporary'
            )
            """
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="ai360 must be a formal account"):
        AuthDatabase(path).initialize()

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute("SELECT * FROM users").fetchone()
        migration = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 4"
        ).fetchone()
    finally:
        connection.close()
    assert row["role"] == "user"
    assert row["password_hash"] == "original-hash"
    assert row["token_version"] == 4
    assert migration is None


def test_root_migration_fails_closed_on_another_root(tmp_path: Path):
    path = tmp_path / "accounts.db"
    database = AuthDatabase(path)
    database.initialize()
    with database.transaction(write=True) as connection:
        connection.execute("DROP INDEX ux_users_single_root")
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            """
            INSERT INTO users(
                id, username, username_normalized, password_hash, role,
                account_type, disabled, token_version, created_at,
                updated_at, created_by
            ) VALUES (
                'usr_conflicting_root', 'other-root', 'other-root', 'hash',
                'root', 'formal', 0, 0, 'created', 'updated', NULL
            )
            """
        )
        connection.execute("DELETE FROM schema_migrations WHERE version = 4")

    with pytest.raises(RuntimeError, match="conflicting ROOT account state"):
        database.initialize()

    with database.transaction() as connection:
        roots = connection.execute(
            "SELECT id FROM users WHERE role = 'root' ORDER BY id"
        ).fetchall()
        migration = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 4"
        ).fetchone()
    assert [row["id"] for row in roots] == ["usr_conflicting_root"]
    assert migration is None

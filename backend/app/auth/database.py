"""SQLite connection setup and idempotent auth schema migrations."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_BUSY_TIMEOUT_MS = 5000

_INITIAL_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        username_normalized TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
        disabled INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0, 1)),
        token_version INTEGER NOT NULL DEFAULT 0 CHECK (token_version >= 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        created_by TEXT REFERENCES users(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_users_role_disabled
    ON users(role, disabled)
    """,
    """
    CREATE TABLE IF NOT EXISTS resources (
        resource_type TEXT NOT NULL CHECK (
            resource_type IN (
                'project',
                'avatar_character',
                'avatar_background',
                'avatar_mascot',
                'custom_voice'
            )
        ),
        resource_id TEXT NOT NULL,
        owner_user_id TEXT REFERENCES users(id) ON DELETE RESTRICT,
        visibility TEXT NOT NULL CHECK (
            visibility IN ('private', 'system_public')
        ),
        created_at TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (resource_type, resource_id),
        CHECK (
            (visibility = 'private' AND owner_user_id IS NOT NULL)
            OR (visibility = 'system_public' AND owner_user_id IS NULL)
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_resources_owner_visibility_type
    ON resources(owner_user_id, visibility, resource_type)
    """,
)

_TEMPORARY_ACCOUNT_STATEMENTS = (
    """
    ALTER TABLE users
    ADD COLUMN account_type TEXT NOT NULL DEFAULT 'formal'
    CHECK (account_type IN ('formal', 'temporary'))
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_users_account_type_disabled
    ON users(account_type, disabled)
    """,
    """
    CREATE TABLE IF NOT EXISTS temporary_account_batches (
        id TEXT PRIMARY KEY,
        created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL,
        revoked_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS temporary_credentials (
        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        batch_id TEXT NOT NULL REFERENCES temporary_account_batches(id)
            ON DELETE CASCADE,
        code_locator TEXT NOT NULL UNIQUE,
        first_used_at TEXT,
        expires_at TEXT,
        duration_seconds INTEGER NOT NULL CHECK (duration_seconds > 0),
        CHECK (
            (first_used_at IS NULL AND expires_at IS NULL)
            OR (first_used_at IS NOT NULL AND expires_at IS NOT NULL)
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_temporary_credentials_batch
    ON temporary_credentials(batch_id, user_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_grants (
        grantee_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        resource_type TEXT NOT NULL,
        resource_id TEXT NOT NULL,
        granted_by TEXT REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (grantee_user_id, resource_type, resource_id),
        FOREIGN KEY (resource_type, resource_id)
            REFERENCES resources(resource_type, resource_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_resource_grants_resource
    ON resource_grants(resource_type, resource_id, grantee_user_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS account_defaults (
        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        project_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        voice_provider TEXT NOT NULL,
        voice_id TEXT NOT NULL,
        mascot_id TEXT NOT NULL DEFAULT '',
        background_id TEXT NOT NULL DEFAULT ''
    )
    """,
)

_ACCOUNT_DEFAULTS_MASCOT_BACKGROUND_STATEMENTS = (
    """
    ALTER TABLE account_defaults
    ADD COLUMN mascot_id TEXT NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE account_defaults
    ADD COLUMN background_id TEXT NOT NULL DEFAULT ''
    """,
)

_MIGRATIONS = (
    (1, "initial_accounts_and_resources", _INITIAL_SCHEMA_STATEMENTS),
    (2, "temporary_accounts_grants_and_defaults", _TEMPORARY_ACCOUNT_STATEMENTS),
    (
        3,
        "account_defaults_mascot_and_background",
        _ACCOUNT_DEFAULTS_MASCOT_BACKGROUND_STATEMENTS,
    ),
)


class AuthDatabase:
    """Open short-lived SQLite connections with consistent safety pragmas."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=_BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return connection

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Apply the current schema exactly once while remaining rerunnable."""
        connection = self.connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
        finally:
            connection.close()

        with self.transaction(write=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    details_json TEXT NOT NULL
                )
                """
            )
            applied_versions = {
                int(row["version"])
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            for version, name, statements in _MIGRATIONS:
                if version in applied_versions:
                    continue
                for index, statement in enumerate(statements):
                    if version == 2 and index == 0:
                        user_columns = {
                            row["name"]
                            for row in connection.execute(
                                "PRAGMA table_info(users)"
                            ).fetchall()
                        }
                        if "account_type" in user_columns:
                            continue
                    if version == 3:
                        defaults_columns = {
                            row["name"]
                            for row in connection.execute(
                                "PRAGMA table_info(account_defaults)"
                            ).fetchall()
                        }
                        if index == 0 and "mascot_id" in defaults_columns:
                            continue
                        if index == 1 and "background_id" in defaults_columns:
                            continue
                    connection.execute(statement)
                connection.execute(
                    """
                    INSERT INTO schema_migrations(version, details_json)
                    VALUES (?, ?)
                    """,
                    (
                        version,
                        json.dumps({"name": name}, separators=(",", ":")),
                    ),
                )

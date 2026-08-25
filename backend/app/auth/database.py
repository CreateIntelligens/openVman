"""SQLite connection setup and idempotent auth schema migrations."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import ROOT_USERNAME

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

_ROOT_ACCOUNT_SCHEMA_VERSION = 4
_ROOT_ACCOUNT_MIGRATION_NAME = "root_account_role_and_auth_audit"
# v5 的 WHERE 條件拿小寫化的 username_normalized 去比對保留原始大小寫的
# locator，永遠不成立，於是被標記完成卻沒遷移到任何一列。改用 v6 重跑。
_TEMPORARY_USERNAME_SCHEMA_VERSION = 6
_TEMPORARY_USERNAME_MIGRATION_NAME = "redact_temporary_credential_locators_v2"

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

        self._migrate_root_account_schema()
        self._redact_temporary_usernames()

    def _redact_temporary_usernames(self) -> None:
        """Remove legacy credential locators from audit-visible usernames."""
        with self.transaction(write=True) as connection:
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (_TEMPORARY_USERNAME_SCHEMA_VERSION,),
            ).fetchone()
            if applied is not None:
                return
            connection.execute(
                """
                UPDATE users
                SET username = 'tmp-' || substr(id, 5),
                    username_normalized = 'tmp-' || substr(id, 5),
                    updated_at = ?
                WHERE account_type = 'temporary'
                  AND EXISTS (
                      SELECT 1 FROM temporary_credentials
                      WHERE temporary_credentials.user_id = users.id
                        -- username_normalized 是小寫化的，locator 保留原始
                        -- 大小寫，直接比對永遠不成立。
                        AND lower(temporary_credentials.code_locator) =
                            users.username_normalized
                  )
                """,
                (datetime.now(timezone.utc).isoformat(),),
            )
            connection.execute(
                """
                INSERT INTO schema_migrations(version, details_json)
                VALUES (?, ?)
                """,
                (
                    _TEMPORARY_USERNAME_SCHEMA_VERSION,
                    json.dumps(
                        {"name": _TEMPORARY_USERNAME_MIGRATION_NAME},
                        separators=(",", ":"),
                    ),
                ),
            )

    def _migrate_root_account_schema(self) -> None:
        """Rebuild users outside FK enforcement, then verify every reference."""
        connection = self.connect()
        try:
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (_ROOT_ACCOUNT_SCHEMA_VERSION,),
            ).fetchone()
            if applied is not None:
                return

            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("BEGIN IMMEDIATE")
            self._apply_root_account_schema(connection)
            connection.execute(
                """
                INSERT INTO schema_migrations(version, details_json)
                VALUES (?, ?)
                """,
                (
                    _ROOT_ACCOUNT_SCHEMA_VERSION,
                    json.dumps(
                        {"name": _ROOT_ACCOUNT_MIGRATION_NAME},
                        separators=(",", ":"),
                    ),
                ),
            )
            connection.commit()
            connection.execute("PRAGMA foreign_keys = ON")
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError("auth migration left invalid foreign keys")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _apply_root_account_schema(connection: sqlite3.Connection) -> None:
        roots = connection.execute(
            "SELECT id, username_normalized, account_type FROM users WHERE role = 'root'"
        ).fetchall()
        if len(roots) > 1 or (
            roots
            and (
                roots[0]["username_normalized"] != ROOT_USERNAME
                or roots[0]["account_type"] != "formal"
            )
        ):
            raise RuntimeError("conflicting ROOT account state")

        root_named = connection.execute(
            "SELECT role, account_type FROM users WHERE username_normalized = ?",
            (ROOT_USERNAME,),
        ).fetchone()
        if root_named is not None and root_named["account_type"] != "formal":
            raise RuntimeError(
                f"{ROOT_USERNAME} must be a formal account before ROOT migration"
            )
        if roots and root_named is None:
            raise RuntimeError(f"ROOT identity must be {ROOT_USERNAME}")

        before_count = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            CREATE TABLE users_root_migration (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                username_normalized TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('root', 'admin', 'user')),
                disabled INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0, 1)),
                token_version INTEGER NOT NULL DEFAULT 0 CHECK (token_version >= 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
                account_type TEXT NOT NULL DEFAULT 'formal'
                    CHECK (account_type IN ('formal', 'temporary'))
            )
            """
        )
        connection.execute(
            """
            INSERT INTO users_root_migration(
                id, username, username_normalized, password_hash, role,
                disabled, token_version, created_at, updated_at, created_by,
                account_type
            )
            SELECT
                id,
                username,
                username_normalized,
                password_hash,
                CASE WHEN username_normalized = ? THEN 'root' ELSE role END,
                disabled,
                token_version + CASE
                    WHEN username_normalized = ? AND role != 'root' THEN 1
                    ELSE 0
                END,
                created_at,
                CASE
                    WHEN username_normalized = ? AND role != 'root' THEN ?
                    ELSE updated_at
                END,
                created_by,
                account_type
            FROM users
            """,
            (ROOT_USERNAME, ROOT_USERNAME, ROOT_USERNAME, now),
        )
        connection.execute("DROP TABLE users")
        connection.execute("ALTER TABLE users_root_migration RENAME TO users")
        connection.execute(
            "CREATE INDEX idx_users_role_disabled ON users(role, disabled)"
        )
        connection.execute(
            """
            CREATE INDEX idx_users_account_type_disabled
            ON users(account_type, disabled)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX ux_users_single_root
            ON users(role) WHERE role = 'root'
            """
        )
        connection.execute(
            """
            CREATE TABLE auth_audit_events (
                id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                actor_user_id TEXT,
                target_user_id TEXT,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX idx_auth_audit_created
            ON auth_audit_events(created_at, id)
            """
        )

        after_count = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        if after_count != before_count:
            raise RuntimeError("auth migration changed the account row count")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("auth migration would violate foreign keys")

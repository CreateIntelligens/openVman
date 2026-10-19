"""SQLite connection setup and idempotent auth schema migrations."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import ROOT_USERNAME
from .schema_migrations import (
    _ACCOUNT_ASR_PROVIDER_SCHEMA_VERSION,
    _ADMIN_PORTAL_ACCESS_MIGRATION_NAME,
    _ADMIN_PORTAL_ACCESS_SCHEMA_VERSION,
    _ASR_ENGINE_RESOURCE_MIGRATION_NAME,
    _ASR_ENGINE_RESOURCE_SCHEMA_VERSION,
    _ASR_ENGINE_RESOURCES_TABLE,
    _KIOSK_MIGRATION_NAME,
    _KIOSK_SCHEMA_VERSION,
    _LAST_LOGIN_MIGRATION_NAME,
    _LAST_LOGIN_SCHEMA_VERSION,
    _MIGRATIONS,
    _PROJECT_RESOURCE_ASSIGNMENTS_TABLE,
    _PROJECT_RESOURCE_SCOPE_MIGRATION_NAME,
    _PROJECT_RESOURCE_SCOPE_RESOURCES_TABLE,
    _PROJECT_RESOURCE_SCOPE_SCHEMA_VERSION,
    _ROOT_ACCOUNT_MIGRATION_NAME,
    _ROOT_ACCOUNT_SCHEMA_VERSION,
    _TEMPORARY_USERNAME_MIGRATION_NAME,
    _TEMPORARY_USERNAME_SCHEMA_VERSION,
)

_BUSY_TIMEOUT_MS = 5000


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
                    if version == 10:
                        credential_columns = {
                            row["name"]
                            for row in connection.execute(
                                "PRAGMA table_info(temporary_credentials)"
                            ).fetchall()
                        }
                        if "password_ciphertext" in credential_columns:
                            continue
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
                    if version == _ACCOUNT_ASR_PROVIDER_SCHEMA_VERSION:
                        # 全新資料庫的基礎 schema 已經含這個欄位，重加會炸。
                        defaults_columns = {
                            row["name"]
                            for row in connection.execute(
                                "PRAGMA table_info(account_defaults)"
                            ).fetchall()
                        }
                        if "asr_provider" in defaults_columns:
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
        self._migrate_asr_engine_resource_type()
        self._redact_temporary_usernames()
        self._add_admin_portal_access()
        self._add_kiosk_flag()
        self._add_last_login_at()
        self._migrate_project_resource_scope()

    def _migrate_project_resource_scope(self) -> None:
        """Allow visibility='project' on resources and add per-project resources and assignments."""
        connection = self.connect()
        try:
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (_PROJECT_RESOURCE_SCOPE_SCHEMA_VERSION,),
            ).fetchone()
            if applied is not None:
                return

            existing = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'resources'"
            ).fetchone()
            if existing is None:
                return

            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(resources)").fetchall()
            }
            needs_rebuild = "owner_project_id" not in columns or "'project'" not in existing["sql"]

            if needs_rebuild:
                connection.execute("PRAGMA foreign_keys = OFF")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(_PROJECT_RESOURCE_SCOPE_RESOURCES_TABLE)
                connection.execute(
                    """
                    INSERT INTO resources_rebuilt(
                        resource_type, resource_id, owner_user_id, visibility,
                        created_at, metadata_json, owner_project_id
                    )
                    SELECT resource_type, resource_id, owner_user_id, visibility,
                           created_at, metadata_json, NULL
                    FROM resources
                    """
                )
                connection.execute("DROP TABLE resources")
                connection.execute("ALTER TABLE resources_rebuilt RENAME TO resources")
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_resources_owner_visibility_type
                    ON resources(owner_user_id, visibility, resource_type)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_resources_owner_project
                    ON resources(owner_project_id, resource_type)
                    """
                )
                connection.commit()
                connection.execute("PRAGMA foreign_keys = ON")
                violations = connection.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise RuntimeError(
                        f"foreign key violations after rebuilding resources: {violations}"
                    )
            else:
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_resources_owner_project
                    ON resources(owner_project_id, resource_type)
                    """
                )
                connection.commit()

            with self.transaction(write=True) as tx_conn:
                policy_columns = {
                    row["name"]
                    for row in tx_conn.execute("PRAGMA table_info(project_policies)").fetchall()
                }
                if "allowed_characters_json" not in policy_columns:
                    tx_conn.execute(
                        "ALTER TABLE project_policies ADD COLUMN allowed_characters_json TEXT NOT NULL DEFAULT '[]'"
                    )
                if "default_character_id" not in policy_columns:
                    tx_conn.execute(
                        "ALTER TABLE project_policies ADD COLUMN default_character_id TEXT"
                    )
                if "allowed_backgrounds_json" not in policy_columns:
                    tx_conn.execute(
                        "ALTER TABLE project_policies ADD COLUMN allowed_backgrounds_json TEXT NOT NULL DEFAULT '[]'"
                    )
                if "default_background_id" not in policy_columns:
                    tx_conn.execute(
                        "ALTER TABLE project_policies ADD COLUMN default_background_id TEXT"
                    )
                if "allowed_mascots_json" not in policy_columns:
                    tx_conn.execute(
                        "ALTER TABLE project_policies ADD COLUMN allowed_mascots_json TEXT NOT NULL DEFAULT '[]'"
                    )
                if "default_mascot_id" not in policy_columns:
                    tx_conn.execute(
                        "ALTER TABLE project_policies ADD COLUMN default_mascot_id TEXT"
                    )
                if "tts_engine_order_json" not in policy_columns:
                    tx_conn.execute(
                        "ALTER TABLE project_policies ADD COLUMN tts_engine_order_json TEXT NOT NULL DEFAULT '[]'"
                    )
                if "asr_engine_order_json" not in policy_columns:
                    tx_conn.execute(
                        "ALTER TABLE project_policies ADD COLUMN asr_engine_order_json TEXT NOT NULL DEFAULT '[]'"
                    )

                tx_conn.execute(_PROJECT_RESOURCE_ASSIGNMENTS_TABLE)
                tx_conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_project_resource_assignments_project
                    ON project_resource_assignments(project_id, resource_type)
                    """
                )
                tx_conn.execute(
                    """
                    INSERT INTO schema_migrations(version, details_json)
                    VALUES (?, ?)
                    """,
                    (
                        _PROJECT_RESOURCE_SCOPE_SCHEMA_VERSION,
                        json.dumps(
                            {"name": _PROJECT_RESOURCE_SCOPE_MIGRATION_NAME},
                            separators=(",", ":"),
                        ),
                    ),
                )
        finally:
            connection.close()

    def _add_last_login_at(self) -> None:
        """Add the nullable last-login timestamp after the ROOT rebuild of users.

        跟 kiosk 一樣不能放進 _MIGRATIONS：ROOT 遷移重建 users 時會丟掉它。
        """
        with self.transaction(write=True) as connection:
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (_LAST_LOGIN_SCHEMA_VERSION,),
            ).fetchone()
            if applied is not None:
                return
            user_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if "last_login_at" not in user_columns:
                connection.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
            connection.execute(
                """
                INSERT INTO schema_migrations(version, details_json)
                VALUES (?, ?)
                """,
                (
                    _LAST_LOGIN_SCHEMA_VERSION,
                    json.dumps(
                        {"name": _LAST_LOGIN_MIGRATION_NAME},
                        separators=(",", ":"),
                    ),
                ),
            )

    def _add_kiosk_flag(self) -> None:
        """Add the default-off kiosk flag after the ROOT rebuild of users.

        不能放進 _MIGRATIONS：全新資料庫會先跑完那串，再由 ROOT 遷移重建
        users 表，重建時沒帶的欄位會整個消失。
        """
        with self.transaction(write=True) as connection:
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (_KIOSK_SCHEMA_VERSION,),
            ).fetchone()
            if applied is not None:
                return
            user_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if "kiosk" not in user_columns:
                connection.execute(
                    """
                    ALTER TABLE users
                    ADD COLUMN kiosk INTEGER NOT NULL DEFAULT 0
                    CHECK (kiosk IN (0, 1))
                    """
                )
            connection.execute(
                """
                INSERT INTO schema_migrations(version, details_json)
                VALUES (?, ?)
                """,
                (
                    _KIOSK_SCHEMA_VERSION,
                    json.dumps(
                        {"name": _KIOSK_MIGRATION_NAME},
                        separators=(",", ":"),
                    ),
                ),
            )

    def _add_admin_portal_access(self) -> None:
        """Add the default-deny portal capability after rebuilding users."""
        with self.transaction(write=True) as connection:
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (_ADMIN_PORTAL_ACCESS_SCHEMA_VERSION,),
            ).fetchone()
            if applied is not None:
                return
            user_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if "admin_portal_access" not in user_columns:
                connection.execute(
                    """
                    ALTER TABLE users
                    ADD COLUMN admin_portal_access INTEGER NOT NULL DEFAULT 0
                    CHECK (admin_portal_access IN (0, 1))
                    """
                )
            connection.execute(
                """
                INSERT INTO schema_migrations(version, details_json)
                VALUES (?, ?)
                """,
                (
                    _ADMIN_PORTAL_ACCESS_SCHEMA_VERSION,
                    json.dumps(
                        {"name": _ADMIN_PORTAL_ACCESS_MIGRATION_NAME},
                        separators=(",", ":"),
                    ),
                ),
            )

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

    def _migrate_asr_engine_resource_type(self) -> None:
        """Widen the resources CHECK so ASR engines can be granted per account.

        SQLite 不能 ALTER 既有的 CHECK，只能重建表。而 resource_grants 與
        admin_resource_scopes 都有外鍵指向它：DROP TABLE 會把授權整批
        CASCADE 掉（實測線上副本掉光全部 920 筆）。

        PRAGMA foreign_keys 在交易中無效，所以必須跟 ROOT 那次遷移一樣，
        在 BEGIN 之前關閉外鍵、提交後再打開並驗證。
        """
        connection = self.connect()
        try:
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (_ASR_ENGINE_RESOURCE_SCHEMA_VERSION,),
            ).fetchone()
            if applied is not None:
                return

            existing = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'resources'"
            ).fetchone()
            if existing is None:
                return
            if "asr_engine" in existing["sql"]:
                # 全新資料庫的基礎 schema 已經允許，只要記錄版本。
                connection.execute(
                    "INSERT INTO schema_migrations(version, details_json) VALUES (?, ?)",
                    (
                        _ASR_ENGINE_RESOURCE_SCHEMA_VERSION,
                        json.dumps(
                            {"name": _ASR_ENGINE_RESOURCE_MIGRATION_NAME},
                            separators=(",", ":"),
                        ),
                    ),
                )
                connection.commit()
                return

            grants_before = int(
                connection.execute("SELECT COUNT(*) FROM resource_grants").fetchone()[0]
            )
            resources_before = int(
                connection.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
            )

            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(_ASR_ENGINE_RESOURCES_TABLE)
            connection.execute(
                """
                INSERT INTO resources_rebuilt(
                    resource_type, resource_id, owner_user_id, visibility,
                    created_at, metadata_json
                )
                SELECT resource_type, resource_id, owner_user_id, visibility,
                       created_at, metadata_json
                FROM resources
                """
            )
            connection.execute("DROP TABLE resources")
            connection.execute("ALTER TABLE resources_rebuilt RENAME TO resources")
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_resources_owner_visibility_type
                ON resources(owner_user_id, visibility, resource_type)
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, details_json) VALUES (?, ?)",
                (
                    _ASR_ENGINE_RESOURCE_SCHEMA_VERSION,
                    json.dumps(
                        {"name": _ASR_ENGINE_RESOURCE_MIGRATION_NAME},
                        separators=(",", ":"),
                    ),
                ),
            )
            connection.commit()
            connection.execute("PRAGMA foreign_keys = ON")

            # 授權掉光是這次遷移最實際的風險，明確驗證而不是只看外鍵。
            grants_after = int(
                connection.execute("SELECT COUNT(*) FROM resource_grants").fetchone()[0]
            )
            resources_after = int(
                connection.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
            )
            if grants_after != grants_before or resources_after != resources_before:
                raise RuntimeError(
                    "asr_engine migration lost rows: "
                    f"grants {grants_before}->{grants_after}, "
                    f"resources {resources_before}->{resources_after}"
                )
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError("asr_engine migration left invalid foreign keys")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

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

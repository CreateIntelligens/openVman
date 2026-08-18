"""Typed repositories for accounts and the ownership registry."""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .database import AuthDatabase
from .models import (
    AccountDefaultsRecord,
    AccountRole,
    AccountType,
    ResourceGrantRecord,
    ResourceRecord,
    ResourceType,
    ResourceVisibility,
    TemporaryBatchRecord,
    TemporaryCredentialRecord,
    UserRecord,
)


class RepositoryError(RuntimeError):
    """Base class for deterministic repository failures."""


class UsernameConflictError(RepositoryError):
    pass


class ResourceConflictError(RepositoryError):
    pass


class UserNotFoundError(RepositoryError):
    pass


class AdminAlreadyExistsError(RepositoryError):
    pass


class SelfProtectionError(RepositoryError):
    pass


class LastAdminError(RepositoryError):
    pass


class AccountEnabledError(RepositoryError):
    pass


class OwnedResourcesError(RepositoryError):
    def __init__(self, counts: dict[str, int]) -> None:
        super().__init__("account owns private resources")
        self.counts = counts


class TemporaryCredentialNotFoundError(RepositoryError):
    pass


class TemporaryCredentialExpiredError(RepositoryError):
    pass


class InvalidResourceGrantError(RepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class TemporaryCredentialCreate:
    locator: str
    password_hash: str


@dataclass(frozen=True, slots=True)
class TemporaryBatchAccount:
    user: UserRecord
    credential: TemporaryCredentialRecord
    grants: tuple[ResourceGrantRecord, ...]
    defaults: AccountDefaultsRecord


@dataclass(frozen=True, slots=True)
class TemporaryBatch:
    batch: TemporaryBatchRecord
    accounts: tuple[TemporaryBatchAccount, ...]


def normalize_username(username: str) -> str:
    normalized = unicodedata.normalize("NFKC", username).strip().casefold()
    if not normalized:
        raise ValueError("username must not be empty")
    return normalized


def _display_username(username: str) -> str:
    display = unicodedata.normalize("NFKC", username).strip()
    if not display:
        raise ValueError("username must not be empty")
    return display


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _user_from_row(row: sqlite3.Row) -> UserRecord:
    return UserRecord(
        id=row["id"],
        username=row["username"],
        username_normalized=row["username_normalized"],
        password_hash=row["password_hash"],
        role=AccountRole(row["role"]),
        account_type=AccountType(row["account_type"]),
        disabled=bool(row["disabled"]),
        token_version=int(row["token_version"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        created_by=row["created_by"],
    )


def _temporary_credential_from_row(
    row: sqlite3.Row,
) -> TemporaryCredentialRecord:
    return TemporaryCredentialRecord(
        user_id=row["user_id"],
        batch_id=row["batch_id"],
        code_locator=row["code_locator"],
        first_used_at=row["first_used_at"],
        expires_at=row["expires_at"],
        duration_seconds=int(row["duration_seconds"]),
    )


def _grant_from_row(row: sqlite3.Row) -> ResourceGrantRecord:
    return ResourceGrantRecord(
        grantee_user_id=row["grantee_user_id"],
        resource_type=ResourceType(row["resource_type"]),
        resource_id=row["resource_id"],
        granted_by=row["granted_by"],
        created_at=row["created_at"],
    )


def _defaults_from_row(row: sqlite3.Row) -> AccountDefaultsRecord:
    return AccountDefaultsRecord(
        user_id=row["user_id"],
        project_id=row["project_id"],
        character_id=row["character_id"],
        voice_provider=row["voice_provider"],
        voice_id=row["voice_id"],
    )


def _resource_from_row(row: sqlite3.Row) -> ResourceRecord:
    return ResourceRecord(
        resource_type=ResourceType(row["resource_type"]),
        resource_id=row["resource_id"],
        owner_user_id=row["owner_user_id"],
        visibility=ResourceVisibility(row["visibility"]),
        created_at=row["created_at"],
        metadata_json=row["metadata_json"],
    )


def _normalize_account_access(
    grants: Iterable[tuple[ResourceType, str]],
    defaults: tuple[str, str, str, str],
) -> tuple[
    tuple[tuple[ResourceType, str], ...],
    tuple[str, str, str, str],
]:
    normalized_grants = tuple(
        sorted(
            {
                (resource_type, resource_id.strip())
                for resource_type, resource_id in grants
                if resource_id.strip()
            },
            key=lambda item: (item[0].value, item[1]),
        )
    )
    required_types = {
        ResourceType.PROJECT,
        ResourceType.AVATAR_CHARACTER,
        ResourceType.CUSTOM_VOICE,
    }
    if {item[0] for item in normalized_grants} != required_types:
        raise InvalidResourceGrantError(
            "project, avatar character, and voice grants are required"
        )

    normalized_defaults = tuple(value.strip() for value in defaults)
    if not all(normalized_defaults):
        raise InvalidResourceGrantError("all account defaults are required")
    project_id, character_id, _voice_provider, voice_id = normalized_defaults
    default_resources = {
        (ResourceType.PROJECT, project_id),
        (ResourceType.AVATAR_CHARACTER, character_id),
        (ResourceType.CUSTOM_VOICE, voice_id),
    }
    if not default_resources.issubset(set(normalized_grants)):
        raise InvalidResourceGrantError(
            "account defaults must be present in the selected grants"
        )
    return normalized_grants, normalized_defaults


def _persist_account_access(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    granted_by: str | None,
    normalized_grants: Sequence[tuple[ResourceType, str]],
    normalized_defaults: tuple[str, str, str, str],
    now: str,
    clear_existing: bool = False,
) -> None:
    for resource_type, resource_id in normalized_grants:
        resource = connection.execute(
            """
            SELECT 1 FROM resources
            WHERE resource_type = ? AND resource_id = ?
            """,
            (resource_type.value, resource_id),
        ).fetchone()
        if resource is None:
            raise InvalidResourceGrantError(
                "resource is not registered: "
                f"{resource_type.value}/{resource_id}"
            )

    if clear_existing:
        connection.execute(
            "DELETE FROM resource_grants WHERE grantee_user_id = ?",
            (user_id,),
        )

    connection.executemany(
        """
        INSERT INTO resource_grants(
            grantee_user_id, resource_type, resource_id,
            granted_by, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                user_id,
                resource_type.value,
                resource_id,
                granted_by,
                now,
            )
            for resource_type, resource_id in normalized_grants
        ],
    )
    project_id, character_id, voice_provider, voice_id = normalized_defaults
    connection.execute(
        """
        INSERT INTO account_defaults(
            user_id, project_id, character_id,
            voice_provider, voice_id
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            project_id = excluded.project_id,
            character_id = excluded.character_id,
            voice_provider = excluded.voice_provider,
            voice_id = excluded.voice_id
        """,
        (
            user_id,
            project_id,
            character_id,
            voice_provider,
            voice_id,
        ),
    )



class UserRepository:
    def __init__(self, database: AuthDatabase) -> None:
        self.database = database

    def create(
        self,
        *,
        username: str,
        password_hash: str,
        role: AccountRole,
        created_by: str | None = None,
        account_type: AccountType = AccountType.FORMAL,
        grants: Iterable[tuple[ResourceType, str]] | None = None,
        defaults: tuple[str, str, str, str] | None = None,
    ) -> UserRecord:
        if (grants is None) != (defaults is None):
            raise InvalidResourceGrantError(
                "account grants and defaults must be provided together"
            )
        normalized_access = (
            _normalize_account_access(grants, defaults)
            if grants is not None and defaults is not None
            else None
        )
        if normalized_access is not None and role is AccountRole.ADMIN:
            raise InvalidResourceGrantError(
                "administrator accounts already have unrestricted access"
            )

        user_id = f"usr_{uuid4().hex}"
        display_username = _display_username(username)
        normalized_username = normalize_username(username)
        now = _now_iso()

        try:
            with self.database.transaction(write=True) as connection:
                if created_by is not None:
                    creator = connection.execute(
                        "SELECT 1 FROM users WHERE id = ?",
                        (created_by,),
                    ).fetchone()
                    if creator is None:
                        raise UserNotFoundError("creator account does not exist")
                connection.execute(
                    """
                    INSERT INTO users(
                        id, username, username_normalized, password_hash, role,
                        account_type, disabled, token_version, created_at,
                        updated_at, created_by
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
                    """,
                    (
                        user_id,
                        display_username,
                        normalized_username,
                        password_hash,
                        role.value,
                        account_type.value,
                        now,
                        now,
                        created_by,
                    ),
                )
                if normalized_access is not None:
                    normalized_grants, normalized_defaults = normalized_access
                    _persist_account_access(
                        connection,
                        user_id=user_id,
                        granted_by=created_by,
                        normalized_grants=normalized_grants,
                        normalized_defaults=normalized_defaults,
                        now=now,
                        clear_existing=False,
                    )
        except sqlite3.IntegrityError as exc:
            if "username_normalized" in str(exc):
                raise UsernameConflictError("username already exists") from exc
            raise

        user = self.get_by_id(user_id)
        if user is None:
            raise RepositoryError("created account could not be reloaded")
        return user

    def create_first_admin(
        self,
        *,
        username: str,
        password_hash: str,
    ) -> UserRecord:
        user_id = f"usr_{uuid4().hex}"
        display_username = _display_username(username)
        normalized_username = normalize_username(username)
        now = _now_iso()

        try:
            with self.database.transaction(write=True) as connection:
                existing = connection.execute(
                    "SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"
                ).fetchone()
                if existing is not None:
                    raise AdminAlreadyExistsError("an administrator already exists")
                connection.execute(
                    """
                    INSERT INTO users(
                        id, username, username_normalized, password_hash, role,
                        account_type, disabled, token_version, created_at,
                        updated_at, created_by
                    ) VALUES (?, ?, ?, ?, 'admin', 'formal', 0, 0, ?, ?, NULL)
                    """,
                    (
                        user_id,
                        display_username,
                        normalized_username,
                        password_hash,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "username_normalized" in str(exc):
                raise UsernameConflictError("username already exists") from exc
            raise

        user = self.get_by_id(user_id)
        if user is None:
            raise RepositoryError("created administrator could not be reloaded")
        return user

    def get_by_id(self, user_id: str) -> UserRecord | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return _user_from_row(row) if row is not None else None

    def get_by_username(self, username: str) -> UserRecord | None:
        try:
            normalized = normalize_username(username)
        except ValueError:
            return None
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username_normalized = ?",
                (normalized,),
            ).fetchone()
        return _user_from_row(row) if row is not None else None

    def list(self) -> list[UserRecord]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM users ORDER BY username_normalized, id"
            ).fetchall()
        return [_user_from_row(row) for row in rows]

    def has_admin(self) -> bool:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"
            ).fetchone()
        return row is not None

    def set_disabled(self, user_id: str, disabled: bool) -> UserRecord:
        with self.database.transaction(write=True) as connection:
            updated = connection.execute(
                """
                UPDATE users SET disabled = ?, updated_at = ? WHERE id = ?
                """,
                (int(disabled), _now_iso(), user_id),
            ).rowcount
            if updated == 0:
                raise UserNotFoundError("account does not exist")
        user = self.get_by_id(user_id)
        if user is None:
            raise RepositoryError("updated account could not be reloaded")
        return user

    def set_disabled_guarded(
        self,
        *,
        actor_id: str,
        user_id: str,
        disabled: bool,
    ) -> UserRecord:
        with self.database.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                raise UserNotFoundError("account does not exist")
            if disabled and actor_id == user_id:
                raise SelfProtectionError("administrator cannot disable itself")
            if (
                disabled
                and row["role"] == AccountRole.ADMIN.value
                and not bool(row["disabled"])
            ):
                enabled_admins = connection.execute(
                    """
                    SELECT COUNT(*) FROM users
                    WHERE role = 'admin' AND disabled = 0
                    """
                ).fetchone()[0]
                if enabled_admins <= 1:
                    raise LastAdminError(
                        "cannot disable the final enabled administrator"
                    )
            connection.execute(
                "UPDATE users SET disabled = ?, updated_at = ? WHERE id = ?",
                (int(disabled), _now_iso(), user_id),
            )
        user = self.get_by_id(user_id)
        if user is None:
            raise RepositoryError("updated account could not be reloaded")
        return user

    def revoke_sessions(self, user_id: str) -> UserRecord:
        with self.database.transaction(write=True) as connection:
            updated = connection.execute(
                """
                UPDATE users
                SET token_version = token_version + 1, updated_at = ?
                WHERE id = ?
                """,
                (_now_iso(), user_id),
            ).rowcount
            if updated == 0:
                raise UserNotFoundError("account does not exist")
        user = self.get_by_id(user_id)
        if user is None:
            raise RepositoryError("updated account could not be reloaded")
        return user

    def delete_guarded(self, *, actor_id: str, user_id: str) -> None:
        with self.database.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                raise UserNotFoundError("account does not exist")
            if actor_id == user_id:
                raise SelfProtectionError("administrator cannot delete itself")
            if not bool(row["disabled"]):
                raise AccountEnabledError("account must be disabled before deletion")

            count_rows = connection.execute(
                """
                SELECT resource_type, COUNT(*) AS resource_count
                FROM resources
                WHERE owner_user_id = ? AND visibility = 'private'
                GROUP BY resource_type
                ORDER BY resource_type
                """,
                (user_id,),
            ).fetchall()
            counts = {
                count_row["resource_type"]: int(count_row["resource_count"])
                for count_row in count_rows
            }
            if counts:
                raise OwnedResourcesError(counts)

            connection.execute("DELETE FROM users WHERE id = ?", (user_id,))


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
    ) -> ResourceRecord:
        normalized_id = resource_id.strip()
        if not normalized_id:
            raise ValueError("resource_id must not be empty")
        if visibility is ResourceVisibility.PRIVATE and owner_user_id is None:
            raise ValueError("private resources require an owner")
        if visibility is ResourceVisibility.SYSTEM_PUBLIC and owner_user_id is not None:
            raise ValueError("system-public resources must not have an owner")

        try:
            with self.database.transaction(write=True) as connection:
                connection.execute(
                    """
                    INSERT INTO resources(
                        resource_type, resource_id, owner_user_id, visibility,
                        created_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resource_type.value,
                        normalized_id,
                        owner_user_id,
                        visibility.value,
                        _now_iso(),
                        json.dumps(
                            metadata or {}, separators=(",", ":"), sort_keys=True
                        ),
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
            deleted = connection.execute(
                """
                DELETE FROM resources
                WHERE resource_type = ? AND resource_id = ?
                """,
                (resource_type.value, resource_id),
            ).rowcount
        return deleted > 0


class AccountAccessRepository:
    """Manage explicit read grants and defaults for any non-admin account."""

    def __init__(self, database: AuthDatabase) -> None:
        self.database = database

    def replace(
        self,
        *,
        user_id: str,
        granted_by: str,
        grants: Iterable[tuple[ResourceType, str]],
        defaults: tuple[str, str, str, str],
    ) -> tuple[tuple[ResourceGrantRecord, ...], AccountDefaultsRecord]:
        normalized_grants, normalized_defaults = _normalize_account_access(
            grants,
            defaults,
        )
        now = _now_iso()
        with self.database.transaction(write=True) as connection:
            actor = connection.execute(
                """
                SELECT role, disabled, account_type FROM users WHERE id = ?
                """,
                (granted_by,),
            ).fetchone()
            if (
                actor is None
                or actor["role"] != AccountRole.ADMIN.value
                or bool(actor["disabled"])
                or actor["account_type"] != AccountType.FORMAL.value
            ):
                raise UserNotFoundError(
                    "enabled formal administrator required"
                )

            target = connection.execute(
                "SELECT role, account_type FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if target is None:
                raise UserNotFoundError("account does not exist")
            if target["account_type"] != AccountType.FORMAL.value:
                raise InvalidResourceGrantError(
                    "temporary account grants are managed by their batch"
                )
            if target["role"] == AccountRole.ADMIN.value:
                raise InvalidResourceGrantError(
                    "administrator accounts already have unrestricted access"
                )

            _persist_account_access(
                connection,
                user_id=user_id,
                granted_by=granted_by,
                normalized_grants=normalized_grants,
                normalized_defaults=normalized_defaults,
                now=now,
                clear_existing=True,
            )

        updated_defaults = self.get_defaults(user_id)
        if updated_defaults is None:
            raise RepositoryError(
                "updated account defaults could not be reloaded"
            )
        return self.list_grants(user_id), updated_defaults

    def get_defaults(self, user_id: str) -> AccountDefaultsRecord | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM account_defaults WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return _defaults_from_row(row) if row is not None else None

    def list_grants(self, user_id: str) -> tuple[ResourceGrantRecord, ...]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM resource_grants
                WHERE grantee_user_id = ?
                ORDER BY resource_type, resource_id
                """,
                (user_id,),
            ).fetchall()
        return tuple(_grant_from_row(row) for row in rows)


class TemporaryAccountRepository:
    """Atomic temporary-credential, grant, and account-default persistence."""

    def __init__(self, database: AuthDatabase) -> None:
        self.database = database

    def create_batch(
        self,
        *,
        created_by: str,
        credentials: Sequence[TemporaryCredentialCreate],
        grants: Iterable[tuple[ResourceType, str]],
        defaults: tuple[str, str, str, str],
        duration_seconds: int,
    ) -> TemporaryBatch:
        if len(credentials) != 5:
            raise ValueError("a temporary batch must contain exactly five credentials")
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")

        normalized_grants, normalized_defaults = _normalize_account_access(
            grants,
            defaults,
        )
        project_id, character_id, voice_provider, voice_id = (
            normalized_defaults
        )

        locators = [credential.locator for credential in credentials]
        if len(set(locators)) != len(credentials) or any(
            not value for value in locators
        ):
            raise ValueError("temporary credential locators must be unique")

        batch_id = f"tmpbatch_{uuid4().hex}"
        now = _now_iso()
        try:
            with self.database.transaction(write=True) as connection:
                creator = connection.execute(
                    """
                    SELECT role, disabled, account_type FROM users WHERE id = ?
                    """,
                    (created_by,),
                ).fetchone()
                if (
                    creator is None
                    or creator["role"] != AccountRole.ADMIN.value
                    or bool(creator["disabled"])
                    or creator["account_type"] != AccountType.FORMAL.value
                ):
                    raise UserNotFoundError(
                        "enabled formal administrator required"
                    )

                for resource_type, resource_id in normalized_grants:
                    resource = connection.execute(
                        """
                        SELECT 1 FROM resources
                        WHERE resource_type = ? AND resource_id = ?
                        """,
                        (resource_type.value, resource_id),
                    ).fetchone()
                    if resource is None:
                        raise InvalidResourceGrantError(
                            "resource is not registered: "
                            f"{resource_type.value}/{resource_id}"
                        )

                connection.execute(
                    """
                    INSERT INTO temporary_account_batches(id, created_by, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (batch_id, created_by, now),
                )
                for credential in credentials:
                    user_id = f"usr_{uuid4().hex}"
                    username = f"Temporary {credential.locator}"
                    connection.execute(
                        """
                        INSERT INTO users(
                            id, username, username_normalized, password_hash,
                            role, account_type, disabled, token_version,
                            created_at, updated_at, created_by
                        ) VALUES (?, ?, ?, ?, 'user', 'temporary', 0, 0, ?, ?, ?)
                        """,
                        (
                            user_id,
                            username,
                            normalize_username(username),
                            credential.password_hash,
                            now,
                            now,
                            created_by,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO temporary_credentials(
                            user_id, batch_id, code_locator, first_used_at,
                            expires_at, duration_seconds
                        ) VALUES (?, ?, ?, NULL, NULL, ?)
                        """,
                        (
                            user_id,
                            batch_id,
                            credential.locator,
                            duration_seconds,
                        ),
                    )
                    _persist_account_access(
                        connection,
                        user_id=user_id,
                        granted_by=created_by,
                        normalized_grants=normalized_grants,
                        normalized_defaults=normalized_defaults,
                        now=now,
                        clear_existing=False,
                    )
        except sqlite3.IntegrityError as exc:
            raise RepositoryError("temporary batch could not be created") from exc

        created = self.get_batch(batch_id)
        if created is None or len(created.accounts) != 5:
            raise RepositoryError("created temporary batch could not be reloaded")
        return created

    def get_credential_by_locator(
        self,
        locator: str,
    ) -> tuple[UserRecord, TemporaryCredentialRecord] | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT users.*, users.id AS user_id,
                       temporary_credentials.batch_id,
                       temporary_credentials.code_locator,
                       temporary_credentials.first_used_at,
                       temporary_credentials.expires_at,
                       temporary_credentials.duration_seconds
                FROM temporary_credentials
                INNER JOIN users ON users.id = temporary_credentials.user_id
                WHERE temporary_credentials.code_locator = ?
                """,
                (locator,),
            ).fetchone()
        if row is None:
            return None
        return _user_from_row(row), _temporary_credential_from_row(row)

    def get_credential_for_user(
        self,
        user_id: str,
    ) -> TemporaryCredentialRecord | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM temporary_credentials WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return _temporary_credential_from_row(row) if row is not None else None

    def activate(
        self,
        *,
        user_id: str,
        now: datetime,
    ) -> tuple[UserRecord, TemporaryCredentialRecord]:
        activated_at = _as_utc(now)
        with self.database.transaction(write=True) as connection:
            row = connection.execute(
                """
                SELECT users.*, users.id AS user_id,
                       temporary_credentials.batch_id,
                       temporary_credentials.code_locator,
                       temporary_credentials.first_used_at,
                       temporary_credentials.expires_at,
                       temporary_credentials.duration_seconds
                FROM temporary_credentials
                INNER JOIN users ON users.id = temporary_credentials.user_id
                WHERE temporary_credentials.user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if row is None or row["account_type"] != AccountType.TEMPORARY.value:
                raise TemporaryCredentialNotFoundError(
                    "temporary credential does not exist"
                )
            if bool(row["disabled"]):
                raise TemporaryCredentialNotFoundError(
                    "temporary credential does not exist"
                )

            if row["first_used_at"] is None:
                expires_at = activated_at + timedelta(
                    seconds=int(row["duration_seconds"])
                )
                connection.execute(
                    """
                    UPDATE temporary_credentials
                    SET first_used_at = ?, expires_at = ?
                    WHERE user_id = ? AND first_used_at IS NULL
                    """,
                    (
                        activated_at.isoformat(),
                        expires_at.isoformat(),
                        user_id,
                    ),
                )
                row = connection.execute(
                    """
                    SELECT users.*, users.id AS user_id,
                           temporary_credentials.batch_id,
                           temporary_credentials.code_locator,
                           temporary_credentials.first_used_at,
                           temporary_credentials.expires_at,
                           temporary_credentials.duration_seconds
                    FROM temporary_credentials
                    INNER JOIN users ON users.id = temporary_credentials.user_id
                    WHERE temporary_credentials.user_id = ?
                    """,
                    (user_id,),
                ).fetchone()

            credential = _temporary_credential_from_row(row)
            if credential.expires_at is None:
                raise RepositoryError("temporary credential activation failed")
            if datetime.fromisoformat(credential.expires_at) <= activated_at:
                raise TemporaryCredentialExpiredError(
                    "temporary credential has expired"
                )
            return _user_from_row(row), credential

    def get_batch(self, batch_id: str) -> TemporaryBatch | None:
        with self.database.transaction() as connection:
            batch_row = connection.execute(
                "SELECT * FROM temporary_account_batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
            if batch_row is None:
                return None
            user_rows = connection.execute(
                """
                SELECT users.*, users.id AS user_id,
                       temporary_credentials.batch_id,
                       temporary_credentials.code_locator,
                       temporary_credentials.first_used_at,
                       temporary_credentials.expires_at,
                       temporary_credentials.duration_seconds
                FROM temporary_credentials
                INNER JOIN users ON users.id = temporary_credentials.user_id
                WHERE temporary_credentials.batch_id = ?
                ORDER BY users.created_at, users.id
                """,
                (batch_id,),
            ).fetchall()
            accounts: list[TemporaryBatchAccount] = []
            for row in user_rows:
                grant_rows = connection.execute(
                    """
                    SELECT * FROM resource_grants
                    WHERE grantee_user_id = ?
                    ORDER BY resource_type, resource_id
                    """,
                    (row["id"],),
                ).fetchall()
                defaults_row = connection.execute(
                    "SELECT * FROM account_defaults WHERE user_id = ?",
                    (row["id"],),
                ).fetchone()
                if defaults_row is None:
                    raise RepositoryError("temporary account defaults are missing")
                accounts.append(
                    TemporaryBatchAccount(
                        user=_user_from_row(row),
                        credential=_temporary_credential_from_row(row),
                        grants=tuple(_grant_from_row(item) for item in grant_rows),
                        defaults=_defaults_from_row(defaults_row),
                    )
                )
        return TemporaryBatch(
            batch=TemporaryBatchRecord(
                id=batch_row["id"],
                created_by=batch_row["created_by"],
                created_at=batch_row["created_at"],
                revoked_at=batch_row["revoked_at"],
            ),
            accounts=tuple(accounts),
        )

    def list_batches(self) -> list[TemporaryBatch]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT id FROM temporary_account_batches
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
        batches = [self.get_batch(row["id"]) for row in rows]
        return [batch for batch in batches if batch is not None]

    def revoke_batch(self, batch_id: str) -> TemporaryBatch:
        now = _now_iso()
        with self.database.transaction(write=True) as connection:
            exists = connection.execute(
                "SELECT 1 FROM temporary_account_batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
            if exists is None:
                raise TemporaryCredentialNotFoundError("temporary batch does not exist")
            connection.execute(
                """
                UPDATE temporary_account_batches
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE id = ?
                """,
                (now, batch_id),
            )
            connection.execute(
                """
                UPDATE users
                SET disabled = 1,
                    token_version = token_version + 1,
                    updated_at = ?
                WHERE id IN (
                    SELECT user_id FROM temporary_credentials WHERE batch_id = ?
                )
                  AND disabled = 0
                """,
                (now, batch_id),
            )
        batch = self.get_batch(batch_id)
        if batch is None:
            raise RepositoryError("revoked temporary batch could not be reloaded")
        return batch

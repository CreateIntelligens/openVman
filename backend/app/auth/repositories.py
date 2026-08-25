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
    AuthAuditEventRecord,
    ResourceGrantRecord,
    ResourceRecord,
    ResourceType,
    ResourceVisibility,
    TemporaryBatchRecord,
    TemporaryCredentialRecord,
    UserRecord,
    is_at_least_admin,
)
from .policy import (
    AccountPolicyError,
    ensure_account_manager,
    ensure_can_change_role,
    ensure_can_create_role,
    ensure_can_manage_account,
    ensure_can_reset_password,
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


def _load_actor_and_target(
    connection: sqlite3.Connection,
    actor_id: str,
    user_id: str,
) -> tuple[UserRecord, UserRecord]:
    """Fetch the acting and target accounts for a guarded mutation.

    Every policy-gated repository method needs exactly this pair, so keeping
    the fetch here means a new method cannot accidentally skip one of them.
    """
    actor = connection.execute(
        "SELECT * FROM users WHERE id = ?",
        (actor_id,),
    ).fetchone()
    if actor is None:
        raise UserNotFoundError("actor account does not exist")
    target = connection.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if target is None:
        raise UserNotFoundError("account does not exist")
    return _user_from_row(actor), _user_from_row(target)


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
    keys = set(row.keys())
    return AccountDefaultsRecord(
        user_id=row["user_id"],
        project_id=row["project_id"],
        character_id=row["character_id"],
        voice_provider=row["voice_provider"],
        voice_id=row["voice_id"],
        mascot_id=row["mascot_id"] or "" if "mascot_id" in keys and row["mascot_id"] else "",
        background_id=row["background_id"] or "" if "background_id" in keys and row["background_id"] else "",
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


def _audit_from_row(row: sqlite3.Row) -> AuthAuditEventRecord:
    return AuthAuditEventRecord(
        id=row["id"],
        action=row["action"],
        actor_user_id=row["actor_user_id"],
        target_user_id=row["target_user_id"],
        created_at=row["created_at"],
        metadata_json=row["metadata_json"],
    )


_AUDIT_SECRET_KEYS = frozenset(
    {"credential", "hash", "jwt", "password", "secret", "token"}
)


def _append_auth_audit(
    connection: sqlite3.Connection,
    *,
    action: str,
    actor_user_id: str | None,
    target_user_id: str | None,
    metadata: dict[str, object] | None = None,
    now: str | None = None,
) -> None:
    safe_metadata = metadata or {}
    for key in safe_metadata:
        normalized = key.casefold()
        if any(secret in normalized for secret in _AUDIT_SECRET_KEYS):
            raise ValueError("audit metadata must not contain secrets")
    connection.execute(
        """
        INSERT INTO auth_audit_events(
            id, action, actor_user_id, target_user_id, created_at, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            f"audit_{uuid4().hex}",
            action,
            actor_user_id,
            target_user_id,
            now or _now_iso(),
            json.dumps(safe_metadata, separators=(",", ":"), sort_keys=True),
        ),
    )


def _normalize_account_access(
    grants: Sequence[tuple[ResourceType, str]],
    defaults: tuple[str, ...],
) -> tuple[tuple[tuple[ResourceType, str], ...], tuple[str, str, str, str, str, str]]:
    normalized_grants = tuple(
        sorted(
            {
                (item[0], item[1].strip())
                for item in grants
                if item[1].strip()
            },
            key=lambda item: (item[0].value, item[1]),
        )
    )
    grant_types = {item[0] for item in normalized_grants}
    required_types = {
        ResourceType.PROJECT,
        ResourceType.CUSTOM_VOICE,
    }
    if not required_types.issubset(grant_types):
        raise InvalidResourceGrantError(
            "project and voice grants are required"
        )
    # 舞台人物可以是 openVman 2D 角色或 VRM，管理端也是併成同一張清單，
    # 所以只要求兩者至少擇一，不強制一定要有 2D 角色。
    if not grant_types & {
        ResourceType.AVATAR_CHARACTER,
        ResourceType.AVATAR_MASCOT,
    }:
        raise InvalidResourceGrantError(
            "at least one avatar character or VRM grant is required"
        )

    normalized_defaults = tuple(value.strip() for value in defaults)
    if len(normalized_defaults) < 4:
        raise InvalidResourceGrantError("all required account defaults are required")
    project_id = normalized_defaults[0]
    character_id = normalized_defaults[1]
    voice_provider = normalized_defaults[2]
    voice_id = normalized_defaults[3]
    mascot_id = normalized_defaults[4] if len(normalized_defaults) > 4 else ""
    background_id = normalized_defaults[5] if len(normalized_defaults) > 5 else ""

    if not all((project_id, voice_provider, voice_id)):
        raise InvalidResourceGrantError("all required account defaults are required")
    # 預設登入人物同樣可以是 2D 角色或 VRM，兩者至少要指定一個。
    if not character_id and not mascot_id:
        raise InvalidResourceGrantError(
            "a default avatar character or VRM is required"
        )

    default_resources = {
        (ResourceType.PROJECT, project_id),
        (ResourceType.CUSTOM_VOICE, voice_id),
    }
    if character_id:
        default_resources.add((ResourceType.AVATAR_CHARACTER, character_id))
    if mascot_id:
        default_resources.add((ResourceType.AVATAR_MASCOT, mascot_id))
    if background_id:
        default_resources.add((ResourceType.AVATAR_BACKGROUND, background_id))

    if not default_resources.issubset(set(normalized_grants)):
        raise InvalidResourceGrantError(
            "account defaults must be present in the selected grants"
        )
    return normalized_grants, (
        project_id,
        character_id,
        voice_provider,
        voice_id,
        mascot_id,
        background_id,
    )


def _persist_account_access(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    granted_by: str | None,
    normalized_grants: Sequence[tuple[ResourceType, str]],
    normalized_defaults: tuple[str, ...],
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
    project_id = normalized_defaults[0]
    character_id = normalized_defaults[1]
    voice_provider = normalized_defaults[2]
    voice_id = normalized_defaults[3]
    mascot_id = normalized_defaults[4] if len(normalized_defaults) > 4 else ""
    background_id = normalized_defaults[5] if len(normalized_defaults) > 5 else ""
    connection.execute(
        """
        INSERT INTO account_defaults(
            user_id, project_id, character_id,
            voice_provider, voice_id,
            mascot_id, background_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            project_id = excluded.project_id,
            character_id = excluded.character_id,
            voice_provider = excluded.voice_provider,
            voice_id = excluded.voice_id,
            mascot_id = excluded.mascot_id,
            background_id = excluded.background_id
        """,
        (
            user_id,
            project_id,
            character_id,
            voice_provider,
            voice_id,
            mascot_id,
            background_id,
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
        if role is AccountRole.ROOT:
            raise AccountPolicyError("ROOT accounts cannot be created")
        if (grants is None) != (defaults is None):
            raise InvalidResourceGrantError(
                "account grants and defaults must be provided together"
            )
        normalized_access = (
            _normalize_account_access(grants, defaults)
            if grants is not None and defaults is not None
            else None
        )
        if normalized_access is not None and is_at_least_admin(role):
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
                        "SELECT * FROM users WHERE id = ?",
                        (created_by,),
                    ).fetchone()
                    if creator is None:
                        raise UserNotFoundError("creator account does not exist")
                    ensure_can_create_role(_user_from_row(creator), role)
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
                if created_by is not None:
                    _append_auth_audit(
                        connection,
                        action="account_created",
                        actor_user_id=created_by,
                        target_user_id=user_id,
                        metadata={
                            "account_type": account_type.value,
                            "role": role.value,
                        },
                        now=now,
                    )
        except sqlite3.IntegrityError as exc:
            if "username_normalized" in str(exc):
                raise UsernameConflictError("username already exists") from exc
            raise

        user = self.get_by_id(user_id)
        if user is None:
            raise RepositoryError("created account could not be reloaded")
        return user

    def create_root(
        self,
        *,
        username: str,
        password_hash: str,
    ) -> UserRecord:
        user_id = f"usr_{uuid4().hex}"
        display_username = _display_username(username)
        normalized_username = normalize_username(username)
        if normalized_username != "ai360":
            raise ValueError("ROOT username must be ai360")
        now = _now_iso()

        try:
            with self.database.transaction(write=True) as connection:
                existing = connection.execute(
                    "SELECT id, username_normalized FROM users WHERE role = 'root' LIMIT 1"
                ).fetchone()
                if existing is not None:
                    raise AdminAlreadyExistsError("ROOT already exists")
                conflicting = connection.execute(
                    "SELECT 1 FROM users WHERE username_normalized = 'ai360'"
                ).fetchone()
                if conflicting is not None:
                    raise UsernameConflictError("ai360 already exists")
                connection.execute(
                    """
                    INSERT INTO users(
                        id, username, username_normalized, password_hash, role,
                        account_type, disabled, token_version, created_at,
                        updated_at, created_by
                    ) VALUES (?, ?, ?, ?, 'root', 'formal', 0, 0, ?, ?, NULL)
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
            raise RepositoryError("created ROOT could not be reloaded")
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

    def list(
        self,
        *,
        account_type: AccountType | None = None,
    ) -> list[UserRecord]:
        query = "SELECT * FROM users"
        params: list[object] = []
        if account_type is not None:
            query += " WHERE account_type = ?"
            params.append(account_type.value)
        query += " ORDER BY username_normalized, id"
        with self.database.transaction() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [_user_from_row(row) for row in rows]

    def has_admin(self) -> bool:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT 1 FROM users WHERE role IN ('root', 'admin') LIMIT 1"
            ).fetchone()
        return row is not None

    def set_disabled_guarded(
        self,
        *,
        actor_id: str,
        user_id: str,
        disabled: bool,
    ) -> UserRecord:
        with self.database.transaction(write=True) as connection:
            actor, target = _load_actor_and_target(connection, actor_id, user_id)
            ensure_can_manage_account(actor, target)
            if disabled and actor_id == user_id:
                raise SelfProtectionError("administrator cannot disable itself")
            if (
                disabled
                and is_at_least_admin(target.role)
                and not target.disabled
            ):
                enabled_admins = connection.execute(
                    """
                    SELECT COUNT(*) FROM users
                    WHERE role IN ('root', 'admin') AND disabled = 0
                    """
                ).fetchone()[0]
                if enabled_admins <= 1:
                    raise LastAdminError(
                        "cannot disable the final enabled administrator"
                    )
            if target.disabled != disabled:
                now = _now_iso()
                connection.execute(
                    """
                    UPDATE users
                    SET disabled = ?, token_version = token_version + 1,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (int(disabled), now, user_id),
                )
                _append_auth_audit(
                    connection,
                    action="account_enabled" if not disabled else "account_disabled",
                    actor_user_id=actor_id,
                    target_user_id=user_id,
                    now=now,
                )
        user = self.get_by_id(user_id)
        if user is None:
            raise RepositoryError("updated account could not be reloaded")
        return user

    def revoke_sessions(
        self,
        user_id: str,
        *,
        actor_id: str,
    ) -> UserRecord:
        with self.database.transaction(write=True) as connection:
            actor, target = _load_actor_and_target(connection, actor_id, user_id)
            ensure_can_manage_account(actor, target)
            now = _now_iso()
            connection.execute(
                """
                UPDATE users
                SET token_version = token_version + 1, updated_at = ?
                WHERE id = ?
                """,
                (now, user_id),
            )
            _append_auth_audit(
                connection,
                action="account_sessions_revoked",
                actor_user_id=actor_id,
                target_user_id=user_id,
                now=now,
            )
        user = self.get_by_id(user_id)
        if user is None:
            raise RepositoryError("updated account could not be reloaded")
        return user

    def delete_guarded(self, *, actor_id: str, user_id: str) -> None:
        with self.database.transaction(write=True) as connection:
            actor, target = _load_actor_and_target(connection, actor_id, user_id)
            ensure_can_manage_account(actor, target)
            if actor_id == user_id:
                raise SelfProtectionError("administrator cannot delete itself")
            if not target.disabled:
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

            now = _now_iso()
            connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
            _append_auth_audit(
                connection,
                action="account_deleted",
                actor_user_id=actor_id,
                target_user_id=user_id,
                metadata={"role": target.role.value},
                now=now,
            )

    def change_role(
        self,
        *,
        actor_id: str,
        user_id: str,
        role: AccountRole,
        grants: Iterable[tuple[ResourceType, str]] | None = None,
        defaults: tuple[str, ...] | None = None,
    ) -> UserRecord:
        if (grants is None) != (defaults is None):
            raise InvalidResourceGrantError(
                "account grants and defaults must be provided together"
            )
        normalized_access = (
            _normalize_account_access(tuple(grants), defaults)
            if grants is not None and defaults is not None
            else None
        )
        with self.database.transaction(write=True) as connection:
            actor, target = _load_actor_and_target(connection, actor_id, user_id)
            ensure_can_change_role(actor, target, role)

            if target.role is role:
                return target
            if role is AccountRole.USER and normalized_access is None:
                raise InvalidResourceGrantError(
                    "demoting an administrator requires grants and defaults"
                )
            if role is AccountRole.ADMIN and normalized_access is not None:
                raise InvalidResourceGrantError(
                    "administrator accounts already have unrestricted access"
                )

            now = _now_iso()
            if role is AccountRole.USER:
                normalized_grants, normalized_defaults = normalized_access
                _persist_account_access(
                    connection,
                    user_id=user_id,
                    granted_by=actor_id,
                    normalized_grants=normalized_grants,
                    normalized_defaults=normalized_defaults,
                    now=now,
                    clear_existing=True,
                )
            else:
                connection.execute(
                    "DELETE FROM resource_grants WHERE grantee_user_id = ?",
                    (user_id,),
                )
                connection.execute(
                    "DELETE FROM account_defaults WHERE user_id = ?",
                    (user_id,),
                )
            connection.execute(
                """
                UPDATE users
                SET role = ?, token_version = token_version + 1, updated_at = ?
                WHERE id = ?
                """,
                (role.value, now, user_id),
            )
            _append_auth_audit(
                connection,
                action="account_role_changed",
                actor_user_id=actor_id,
                target_user_id=user_id,
                metadata={"from_role": target.role.value, "to_role": role.value},
                now=now,
            )

        updated = self.get_by_id(user_id)
        if updated is None:
            raise RepositoryError("updated account could not be reloaded")
        return updated

    def reset_password(
        self,
        *,
        actor_id: str,
        user_id: str,
        password_hash: str,
    ) -> UserRecord:
        with self.database.transaction(write=True) as connection:
            actor, target = _load_actor_and_target(connection, actor_id, user_id)
            ensure_can_reset_password(actor, target)

            now = _now_iso()
            connection.execute(
                """
                UPDATE users
                SET password_hash = ?, token_version = token_version + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (password_hash, now, user_id),
            )
            _append_auth_audit(
                connection,
                action="account_password_reset",
                actor_user_id=actor_id,
                target_user_id=user_id,
                now=now,
            )

        updated = self.get_by_id(user_id)
        if updated is None:
            raise RepositoryError("updated account could not be reloaded")
        return updated

    def recover_root_password(self, *, password_hash: str) -> UserRecord:
        """Replace the sole ROOT password for a container-local operator."""
        with self.database.transaction(write=True) as connection:
            roots = connection.execute(
                "SELECT * FROM users WHERE role = 'root'"
            ).fetchall()
            if len(roots) != 1:
                raise RepositoryError("exactly one ROOT account is required")
            root = _user_from_row(roots[0])
            if (
                root.username_normalized != "ai360"
                or root.account_type is not AccountType.FORMAL
            ):
                raise RepositoryError("ROOT identity is invalid")
            now = _now_iso()
            connection.execute(
                """
                UPDATE users
                SET password_hash = ?, token_version = token_version + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (password_hash, now, root.id),
            )
            _append_auth_audit(
                connection,
                action="root_password_recovered",
                actor_user_id=None,
                target_user_id=root.id,
                now=now,
            )

        updated = self.get_by_id(root.id)
        if updated is None:
            raise RepositoryError("recovered ROOT could not be reloaded")
        return updated

    def change_own_password(
        self,
        *,
        user_id: str,
        password_hash: str,
    ) -> UserRecord:
        with self.database.transaction(write=True) as connection:
            user = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if user is None:
                raise UserNotFoundError("account does not exist")
            if user["account_type"] != AccountType.FORMAL.value:
                raise AccountPolicyError(
                    "temporary account passwords cannot be changed"
                )
            now = _now_iso()
            connection.execute(
                """
                UPDATE users
                SET password_hash = ?, token_version = token_version + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (password_hash, now, user_id),
            )
            _append_auth_audit(
                connection,
                action="own_password_changed",
                actor_user_id=user_id,
                target_user_id=user_id,
                now=now,
            )

        updated = self.get_by_id(user_id)
        if updated is None:
            raise RepositoryError("updated account could not be reloaded")
        return updated


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
                    _now_iso(),
                    json.dumps(
                        metadata or {}, separators=(",", ":"), sort_keys=True
                    ),
                ),
            )
        record = self.get(resource_type, normalized_id)
        if record is None:
            raise RepositoryError("upserted resource could not be reloaded")
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
    """Manage explicit read grants and defaults for any scoped account."""

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
                "SELECT * FROM users WHERE id = ?",
                (granted_by,),
            ).fetchone()
            if actor is None:
                raise UserNotFoundError("administrator account does not exist")

            target = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if target is None:
                raise UserNotFoundError("account does not exist")
            ensure_can_manage_account(_user_from_row(actor), _user_from_row(target))
            if target["account_type"] != AccountType.FORMAL.value:
                raise InvalidResourceGrantError(
                    "temporary account grants are managed by their batch"
                )
            if is_at_least_admin(AccountRole(target["role"])):
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
            _append_auth_audit(
                connection,
                action="account_access_updated",
                actor_user_id=granted_by,
                target_user_id=user_id,
                now=now,
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
        (
            project_id,
            character_id,
            voice_provider,
            voice_id,
            mascot_id,
            background_id,
        ) = normalized_defaults

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
                    "SELECT * FROM users WHERE id = ?",
                    (created_by,),
                ).fetchone()
                if creator is None:
                    raise UserNotFoundError("administrator account does not exist")
                ensure_account_manager(_user_from_row(creator))

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
                    # Login lookup uses a hidden password prefix; the account name
                    # must remain unrelated so later audit responses cannot reveal it.
                    username = f"tmp-{uuid4().hex}"
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
                _append_auth_audit(
                    connection,
                    action="temporary_batch_created",
                    actor_user_id=created_by,
                    target_user_id=None,
                    metadata={"account_count": len(credentials), "batch_id": batch_id},
                    now=now,
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
                raise TemporaryCredentialExpiredError(
                    "temporary credential batch has been revoked"
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

    def revoke_batch(
        self,
        batch_id: str,
        *,
        actor_id: str,
    ) -> TemporaryBatch:
        now = _now_iso()
        with self.database.transaction(write=True) as connection:
            actor = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (actor_id,),
            ).fetchone()
            if actor is None:
                raise UserNotFoundError("administrator account does not exist")
            ensure_account_manager(_user_from_row(actor))
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
            _append_auth_audit(
                connection,
                action="temporary_batch_revoked",
                actor_user_id=actor_id,
                target_user_id=None,
                metadata={"batch_id": batch_id},
                now=now,
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

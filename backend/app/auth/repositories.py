"""Typed repositories for accounts and the ownership registry."""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from ._repository_base import RepositoryError, now_iso
from .database import AuthDatabase
from .models import (
    ADMIN_OR_ABOVE_VALUES,
    ROOT_USERNAME,
    AccountDefaultsRecord,
    AccountRole,
    AccountType,
    AdminScope,
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


class InvalidResourceGrantError(RepositoryError):
    pass


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
        admin_portal_access=bool(row["admin_portal_access"]),
    )


_ADMIN_OR_ABOVE_PLACEHOLDERS = ", ".join("?" * len(ADMIN_OR_ABOVE_VALUES))


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
        mascot_id=(row["mascot_id"] or "") if "mascot_id" in keys else "",
        background_id=(row["background_id"] or "") if "background_id" in keys else "",
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
            now or now_iso(),
            json.dumps(safe_metadata, separators=(",", ":"), sort_keys=True),
        ),
    )


def _normalize_account_access(
    grants: Iterable[tuple[ResourceType, str]],
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

    if not all((project_id, voice_id)):
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


def _ensure_grants_within_granter_scope(
    connection: sqlite3.Connection,
    *,
    granted_by: str | None,
    normalized_grants: Sequence[tuple[ResourceType, str]],
) -> None:
    """Refuse grants that exceed the granting administrator's own ceiling.

    This is what makes the ceiling transitive: an administrator restricted to
    two voices can only ever hand out those two, and any account it creates
    inherits that same limit.
    """
    if granted_by is None:
        return
    granter = connection.execute(
        "SELECT * FROM users WHERE id = ?",
        (granted_by,),
    ).fetchone()
    if granter is None:
        return
    if AccountRole(granter["role"]) is AccountRole.ROOT:
        return
    scope = _load_admin_scope(connection, granted_by)
    if not scope.scoped:
        return
    outside = [
        (resource_type, resource_id)
        for resource_type, resource_id in normalized_grants
        if (resource_type, resource_id) not in scope.resources
    ]
    if outside:
        detail = ", ".join(
            f"{resource_type.value}/{resource_id}"
            for resource_type, resource_id in sorted(
                outside, key=lambda item: (item[0].value, item[1]),
            )
        )
        raise InvalidResourceGrantError(
            "cannot grant resources outside your assigned scope: " + detail
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
    _ensure_grants_within_granter_scope(
        connection,
        granted_by=granted_by,
        normalized_grants=normalized_grants,
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
    voice_id = normalized_defaults[3]
    # Registered metadata wins over a stale client selection. Legacy resources
    # without provider metadata still need the administrator's explicit choice.
    voice_provider = (
        _voice_provider_of(connection, voice_id) or normalized_defaults[2]
    )
    if not voice_provider or voice_provider == "auto":
        raise InvalidResourceGrantError("a concrete voice provider is required")
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
                        now_iso(),
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


def _load_admin_scope(
    connection: sqlite3.Connection,
    admin_user_id: str,
) -> AdminScope:
    state = connection.execute(
        "SELECT scoped FROM admin_scope_state WHERE admin_user_id = ?",
        (admin_user_id,),
    ).fetchone()
    if state is None or not int(state["scoped"]):
        return AdminScope(
            admin_user_id=admin_user_id,
            scoped=False,
            resources=frozenset(),
        )
    rows = connection.execute(
        """
        SELECT resource_type, resource_id FROM admin_resource_scopes
        WHERE admin_user_id = ?
        """,
        (admin_user_id,),
    ).fetchall()
    return AdminScope(
        admin_user_id=admin_user_id,
        scoped=True,
        resources=frozenset(
            (ResourceType(row["resource_type"]), row["resource_id"])
            for row in rows
        ),
    )


def _inherit_admin_scope(
    connection: sqlite3.Connection,
    *,
    admin_user_id: str,
    created_by: str,
    now: str,
) -> None:
    """Copy the creator's ceiling onto a newly created administrator.

    不設限的建立者（ROOT，或尚未被指派上限的 admin）不留下任何列，維持
    既有部署「沒設過就不設限」的行為。
    """
    creator_scope = _load_admin_scope(connection, created_by)
    if not creator_scope.scoped:
        return
    connection.execute(
        """
        INSERT INTO admin_scope_state(admin_user_id, scoped, updated_by, updated_at)
        VALUES (?, 1, ?, ?)
        ON CONFLICT(admin_user_id) DO UPDATE SET
            scoped = 1, updated_by = excluded.updated_by,
            updated_at = excluded.updated_at
        """,
        (admin_user_id, created_by, now),
    )
    connection.executemany(
        """
        INSERT INTO admin_resource_scopes(
            admin_user_id, resource_type, resource_id, granted_by, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            (admin_user_id, resource_type.value, resource_id, created_by, now)
            for resource_type, resource_id in sorted(
                creator_scope.resources,
                key=lambda item: (item[0].value, item[1]),
            )
        ],
    )


def _narrow_subordinate_scopes(
    connection: sqlite3.Connection,
    *,
    admin_user_id: str,
    allowed: Sequence[tuple[ResourceType, str]],
    updated_by: str,
    now: str,
) -> int:
    """Clamp every descendant administrator to the shrunken ceiling.

    收斂必須沿著委派鏈往下走：上層被縮權後，下屬保留原範圍的話，上層只要
    先委派再被縮權就能透過下屬保住資源。每層都要跟著撤掉超出的授權。
    """
    allowed_set = {(item[0].value, item[1]) for item in allowed}
    narrowed = 0
    pending = [admin_user_id]
    seen = {admin_user_id}
    while pending:
        current = pending.pop()
        children = connection.execute(
            f"""
            SELECT id FROM users
            WHERE created_by = ? AND role IN ({_ADMIN_OR_ABOVE_PLACEHOLDERS})
            """,
            (current, *ADMIN_OR_ABOVE_VALUES),
        ).fetchall()
        for child in children:
            child_id = child["id"]
            if child_id in seen:
                continue
            seen.add(child_id)
            pending.append(child_id)

            child_scope = _load_admin_scope(connection, child_id)
            kept = [
                (resource_type, resource_id)
                for resource_type, resource_id in child_scope.resources
                if (resource_type.value, resource_id) in allowed_set
            ]
            if child_scope.scoped and len(kept) == len(child_scope.resources):
                continue

            connection.execute(
                """
                INSERT INTO admin_scope_state(
                    admin_user_id, scoped, updated_by, updated_at
                ) VALUES (?, 1, ?, ?)
                ON CONFLICT(admin_user_id) DO UPDATE SET
                    scoped = 1, updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (child_id, updated_by, now),
            )
            connection.execute(
                "DELETE FROM admin_resource_scopes WHERE admin_user_id = ?",
                (child_id,),
            )
            if kept:
                connection.executemany(
                    """
                    INSERT INTO admin_resource_scopes(
                        admin_user_id, resource_type, resource_id,
                        granted_by, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (child_id, rt.value, rid, updated_by, now)
                        for rt, rid in sorted(
                            kept, key=lambda item: (item[0].value, item[1]),
                        )
                    ],
                )
            _revoke_grants_outside_scope(
                connection, admin_user_id=child_id, allowed=kept,
            )
            narrowed += 1
    return narrowed


def _revoke_grants_outside_scope(
    connection: sqlite3.Connection,
    *,
    admin_user_id: str,
    allowed: Sequence[tuple[ResourceType, str]],
) -> int:
    """Drop grants this administrator issued that its new ceiling excludes."""
    rows = connection.execute(
        """
        SELECT grantee_user_id, resource_type, resource_id
        FROM resource_grants
        WHERE granted_by = ?
        """,
        (admin_user_id,),
    ).fetchall()
    allowed_set = {(item[0].value, item[1]) for item in allowed}
    stale = [
        (row["grantee_user_id"], row["resource_type"], row["resource_id"])
        for row in rows
        if (row["resource_type"], row["resource_id"]) not in allowed_set
    ]
    if not stale:
        return 0
    connection.executemany(
        """
        DELETE FROM resource_grants
        WHERE grantee_user_id = ? AND resource_type = ? AND resource_id = ?
        """,
        stale,
    )
    for grantee_user_id in {item[0] for item in stale}:
        _repoint_dangling_defaults(connection, user_id=grantee_user_id)
    return len(stale)


# account_defaults 的欄位名稱對應到哪一種資源。預設值是登入時真正套用的
# 東西，撤銷授權卻留著預設值等於沒撤——帳號會繼續用那個資源。
_DEFAULT_COLUMNS: tuple[tuple[str, ResourceType], ...] = (
    ("project_id", ResourceType.PROJECT),
    ("character_id", ResourceType.AVATAR_CHARACTER),
    ("voice_id", ResourceType.CUSTOM_VOICE),
    ("mascot_id", ResourceType.AVATAR_MASCOT),
    ("background_id", ResourceType.AVATAR_BACKGROUND),
)




def _voice_provider_of(connection: sqlite3.Connection, voice_id: str) -> str:
    row = connection.execute(
        "SELECT metadata_json FROM resources WHERE resource_type = ? AND resource_id = ?",
        (ResourceType.CUSTOM_VOICE.value, voice_id),
    ).fetchone()
    if row is None:
        return ""
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except (TypeError, ValueError):
        return ""
    provider = metadata.get("provider") if isinstance(metadata, dict) else None
    return provider.strip() if isinstance(provider, str) else ""


def _repoint_dangling_defaults(
    connection: sqlite3.Connection,
    *,
    user_id: str,
) -> None:
    """Point defaults that lost their grant at another granted resource.

    優先改指向同類型仍有授權的資源；真的沒有了才留空，讓帳號在下次設定時
    被迫重新選，而不是靜默沿用一個已被撤銷的資源。
    """
    row = connection.execute(
        "SELECT * FROM account_defaults WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return

    updates: dict[str, str] = {}
    for column, resource_type in _DEFAULT_COLUMNS:
        current = row[column]
        if not current:
            continue
        still_granted = connection.execute(
            """
            SELECT 1 FROM resource_grants
            WHERE grantee_user_id = ? AND resource_type = ? AND resource_id = ?
            """,
            (user_id, resource_type.value, current),
        ).fetchone()
        if still_granted is not None:
            continue
        replacements = connection.execute(
            """
            SELECT resource_id FROM resource_grants
            WHERE grantee_user_id = ? AND resource_type = ?
            ORDER BY resource_id
            """,
            (user_id, resource_type.value),
        ).fetchall()
        if resource_type is ResourceType.CUSTOM_VOICE:
            # 換聲線時不能把舊 provider 猜給新資源。略過無法辨識 provider
            # 的聲線；都無法辨識時成對清空，等待管理員重新指派。
            updates[column] = ""
            updates["voice_provider"] = ""
            for replacement in replacements:
                provider = _voice_provider_of(
                    connection, replacement["resource_id"],
                )
                if provider and provider != "auto":
                    updates[column] = replacement["resource_id"]
                    updates["voice_provider"] = provider
                    break
        else:
            updates[column] = (
                replacements[0]["resource_id"] if replacements else ""
            )

    if not updates:
        return
    assignments = ", ".join(f"{column} = ?" for column in updates)
    connection.execute(
        f"UPDATE account_defaults SET {assignments} WHERE user_id = ?",
        (*updates.values(), user_id),
    )


# 呼叫端歷來從這裡 import 各 repository 的符號，維持原入口；__all__ 同時保留
# 帳號 repository 的公開介面，避免拆分後星號匯入只剩 embed key。
from .account_access_repository import AccountAccessRepository
from .user_repository import UserRepository
from .admin_scopes_repository import AdminScopeRepository
from .temporary_accounts_repository import (
    TemporaryAccountRepository,
    TemporaryBatch,
    TemporaryBatchAccount,
    TemporaryCredentialCreate,
    TemporaryCredentialExpiredError,
    TemporaryCredentialNotFoundError,
)

from .embed_keys_repository import (
    DEFAULT_DAILY_REQUEST_QUOTA,
    DEFAULT_RATE_LIMIT_PER_MINUTE,
    EMBED_KEY_PREFIX,
    EMBED_KEY_RANDOM_CHARS,
    EmbedKeyNotFoundError,
    EmbedKeyRepository,
    generate_embed_key_id,
    utc_day,
)

__all__ = [
    "DEFAULT_DAILY_REQUEST_QUOTA",
    "DEFAULT_RATE_LIMIT_PER_MINUTE",
    "EMBED_KEY_PREFIX",
    "EMBED_KEY_RANDOM_CHARS",
    "AccountAccessRepository",
    "AccountEnabledError",
    "AdminAlreadyExistsError",
    "AdminScopeRepository",
    "AuthAuditRepository",
    "EmbedKeyNotFoundError",
    "EmbedKeyRepository",
    "InvalidResourceGrantError",
    "LastAdminError",
    "OwnedResourcesError",
    "RepositoryError",
    "ResourceConflictError",
    "ResourceRepository",
    "SelfProtectionError",
    "TemporaryAccountRepository",
    "TemporaryBatch",
    "TemporaryBatchAccount",
    "TemporaryCredentialCreate",
    "TemporaryCredentialExpiredError",
    "TemporaryCredentialNotFoundError",
    "UserNotFoundError",
    "UserRepository",
    "UsernameConflictError",
    "generate_embed_key_id",
    "normalize_username",
    "utc_day",
]

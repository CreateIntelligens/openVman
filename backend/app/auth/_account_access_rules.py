"""Validation and persistence of account grants and login defaults."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence

from ._admin_scope_rules import _load_admin_scope, _voice_provider_of
from .models import AccountRole, AdminScope, ProjectWritePermissions, ResourceType, UserRecord
from .policy import AccountPolicyError
from .repository_errors import InvalidResourceGrantError


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
    # 人物與小助理在管理端併成同一張清單，只要求兩者至少擇一，
    # 不強制一定要有 2D 角色。
    if not grant_types & {
        ResourceType.AVATAR_CHARACTER,
        ResourceType.AVATAR_MASCOT,
    }:
        raise InvalidResourceGrantError(
            "at least one avatar character or mascot grant is required"
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
    # 預設值同樣是人物或小助理至少指定一個。
    if not character_id and not mascot_id:
        raise InvalidResourceGrantError(
            "a default avatar character or mascot is required"
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
    normalized_defaults: tuple[str, ...] | None,
    now: str,
    clear_existing: bool = False,
    project_permissions: Mapping[str, ProjectWritePermissions] | None = None,
    legacy_project_edit: bool = False,
) -> None:
    _ensure_grants_within_granter_scope(
        connection,
        granted_by=granted_by,
        normalized_grants=normalized_grants,
    )
    account = connection.execute(
        "SELECT vendor_name FROM users WHERE id = ?", (user_id,),
    ).fetchone()
    vendor_name = account["vendor_name"]
    projects = {rid for kind, rid in normalized_grants if kind is ResourceType.PROJECT}
    if project_permissions is not None and set(project_permissions) - projects:
        raise InvalidResourceGrantError(
            "project write permissions require a selected project"
        )
    explicit = project_permissions is not None
    prior_writes = {}
    if not explicit and clear_existing:
        prior_writes = {
            row["resource_id"]: ProjectWritePermissions(
                bool(row["edit_knowledge"]), bool(row["edit_settings"])
            )
            for row in connection.execute(
                """
                SELECT resource_id, edit_knowledge, edit_settings FROM resource_grants
                WHERE grantee_user_id = ? AND resource_type = 'project'
                  AND project_writes_explicit = 1
                """,
                (user_id,),
            )
        }
    write_flags = {}
    for resource_type, resource_id in normalized_grants:
        resource = connection.execute(
            """
            SELECT vendor_name FROM resources
            WHERE resource_type = ? AND resource_id = ?
            """,
            (resource_type.value, resource_id),
        ).fetchone()
        if resource is None:
            raise InvalidResourceGrantError(
                "resource is not registered: "
                f"{resource_type.value}/{resource_id}"
            )
        if resource_type is not ResourceType.PROJECT:
            continue
        if vendor_name and resource["vendor_name"] != vendor_name:
            raise InvalidResourceGrantError("帳號與專案的所屬廠商必須相同")
        if explicit:
            writes = project_permissions.get(resource_id, ProjectWritePermissions())
            if vendor_name and writes.edit_settings:
                raise InvalidResourceGrantError("廠商帳號不可取得其他設定的編輯權限")
        else:
            legacy = legacy_project_edit and not vendor_name
            writes = prior_writes.get(resource_id, ProjectWritePermissions(legacy, legacy))
            if vendor_name and writes.edit_settings:
                writes = ProjectWritePermissions(edit_knowledge=writes.edit_knowledge)
        write_flags[resource_id] = (
            writes.edit_knowledge, writes.edit_settings,
            explicit or resource_id in prior_writes,
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
            granted_by, created_at, edit_knowledge, edit_settings, project_writes_explicit
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                user_id,
                resource_type.value,
                resource_id,
                granted_by,
                now,
                *(
                    write_flags[resource_id]
                    if resource_type is ResourceType.PROJECT
                    else (False, False, False)
                ),
            )
            for resource_type, resource_id in normalized_grants
        ],
    )

    if normalized_defaults is None:
        return

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


def ensure_vendor_target_within_scope(
    connection: sqlite3.Connection,
    actor: UserRecord,
    target: UserRecord,
) -> None:
    if actor.role is AccountRole.ROOT or not target.vendor_name:
        return
    scope = _load_admin_scope(connection, actor.id)
    if not vendor_target_within_scope(connection, scope, target.id):
        raise AccountPolicyError("target resources exceed administrator access")


def vendor_target_within_scope(
    connection: sqlite3.Connection,
    scope: AdminScope,
    user_id: str,
) -> bool:
    if not scope.scoped:
        return True
    rows = connection.execute(
        """
        SELECT resource_type, resource_id FROM resource_grants WHERE grantee_user_id = ?
        UNION
        SELECT resource_type, resource_id FROM resources WHERE owner_user_id = ?
        """,
        (user_id, user_id),
    )
    # 重設密碼可取得該帳號的操作能力，仍須遵守管理員的資源上限。
    return all(
        scope.allows(ResourceType(row["resource_type"]), row["resource_id"])
        for row in rows
    )

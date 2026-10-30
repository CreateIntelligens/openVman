"""Validation and persistence of account grants and login defaults."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence

from ._admin_scope_rules import _load_admin_scope, _voice_provider_of
from .models import AccountRole, ResourceType
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

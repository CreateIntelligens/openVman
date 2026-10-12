"""Shared row converters, username rules, and audit writes."""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from uuid import uuid4

from ._repository_base import now_iso
from .models import (
    ADMIN_OR_ABOVE_VALUES,
    AccountDefaultsRecord,
    AccountRole,
    AccountType,
    ResourceGrantRecord,
    ResourceType,
    UserRecord,
)
from .repository_errors import UserNotFoundError


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
        kiosk=bool(row["kiosk"]),
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

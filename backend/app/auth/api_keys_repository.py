"""Account-owned opaque credentials with atomic validation and usage tracking."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from ._account_records import (
    _append_auth_audit,
    _load_actor_and_target,
    _user_from_row,
)
from .admin_scopes_repository import AdminScopeRepository
from .database import AuthDatabase
from .models import (
    AccountRole,
    AccountType,
    ApiKeyRecord,
    ResourceType,
    UserRecord,
)
from .policy import AccountPolicyError, ensure_can_manage_account
from .resource_repository import ResourceRepository
from .resources import list_accessible_resources

_KEY_PATTERN = re.compile(r"ovk_([a-f0-9]{32})\.[A-Za-z0-9_-]{43}")


class InvalidApiKeyError(ValueError):
    """The credential or its owning account is no longer valid."""


class ApiKeyNotFoundError(LookupError):
    pass


def _record(row: sqlite3.Row) -> ApiKeyRecord:
    return ApiKeyRecord(
        key_id=row["key_id"],
        user_id=row["user_id"],
        label=row["label"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        last_used_at=row["last_used_at"],
        request_count=int(row["request_count"]),
        token_prefix=f"ovk_{row['key_id']}",
    )


def _authorize(
    connection: sqlite3.Connection,
    actor_id: str,
    user_id: str,
) -> UserRecord:
    actor, target = _load_actor_and_target(connection, actor_id, user_id)
    if actor.disabled or actor.account_type is not AccountType.FORMAL:
        raise AccountPolicyError("formal active account required")
    if target.account_type is not AccountType.FORMAL:
        raise AccountPolicyError("API keys require a formal account")
    if actor.id != target.id:
        ensure_can_manage_account(actor, target)
    return target


def _ensure_creation_ceiling(
    actor: UserRecord, target: UserRecord, database: AuthDatabase
) -> None:
    if actor.id == target.id or actor.role is AccountRole.ROOT:
        return
    # 代發他人的 admin key 也會取得管理其直屬帳號的權力，因此僅 ROOT 可代發。
    if target.role is not AccountRole.USER:
        raise AccountPolicyError(
            "only ROOT can issue other administrator keys"
        )
    resources = ResourceRepository(database)
    scopes = AdminScopeRepository(database)
    for resource_type in ResourceType:
        allowed = {
            item.resource_id
            for item in list_accessible_resources(
                resources, actor, resource_type, admin_scopes=scopes
            )
        }
        target_resources = list_accessible_resources(
            resources, target, resource_type, admin_scopes=scopes
        )
        if any(item.resource_id not in allowed for item in target_resources):
            raise AccountPolicyError("target resources exceed issuer access")


class ApiKeyRepository:
    def __init__(self, database: AuthDatabase) -> None:
        self.database = database

    def create(
        self,
        *,
        actor_id: str,
        user_id: str,
        label: str,
        expires_at: datetime | None = None,
    ) -> tuple[ApiKeyRecord, str]:
        label = label.strip()
        if not label or len(label) > 120:
            raise ValueError("label must contain 1 to 120 characters")
        now = datetime.now(timezone.utc)
        if expires_at is not None:
            if expires_at.tzinfo is None or expires_at <= now:
                raise ValueError(
                    "expires_at must be a future timezone-aware date"
                )
            expires_at = expires_at.astimezone(timezone.utc)
        key_id = uuid4().hex
        credential = f"ovk_{key_id}.{secrets.token_urlsafe(32)}"
        digest = hashlib.sha256(credential.encode("ascii")).hexdigest()
        with self.database.transaction(write=True) as connection:
            target = _authorize(connection, actor_id, user_id)
            if target.disabled:
                raise AccountPolicyError("API keys require an active account")
            actor, _ = _load_actor_and_target(connection, actor_id, user_id)
            _ensure_creation_ceiling(actor, target, self.database)
            connection.execute(
                """
                INSERT INTO account_api_keys (
                    key_id, user_id, label, credential_digest, issued_role,
                    issued_token_version, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key_id,
                    user_id,
                    label,
                    digest,
                    target.role.value,
                    target.token_version,
                    now.isoformat(),
                    expires_at.isoformat() if expires_at else None,
                ),
            )
            _append_auth_audit(
                connection,
                action="api_key.created",
                actor_user_id=actor_id,
                target_user_id=user_id,
                metadata={"key_id": key_id},
                now=now.isoformat(),
            )
            row = connection.execute(
                "SELECT * FROM account_api_keys WHERE key_id = ?", (key_id,)
            ).fetchone()
        return _record(row), credential

    def list_for_user(
        self, *, actor_id: str, user_id: str
    ) -> tuple[ApiKeyRecord, ...]:
        with self.database.transaction() as connection:
            _authorize(connection, actor_id, user_id)
            rows = connection.execute(
                """
                SELECT * FROM account_api_keys WHERE user_id = ?
                ORDER BY created_at DESC, key_id
                """,
                (user_id,),
            ).fetchall()
        return tuple(_record(row) for row in rows)

    def revoke(self, *, actor_id: str, key_id: str) -> None:
        with self.database.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM account_api_keys WHERE key_id = ?", (key_id,)
            ).fetchone()
            if row is None:
                raise ApiKeyNotFoundError("API key not found")
            _authorize(connection, actor_id, row["user_id"])
            if row["revoked_at"] is not None:
                return
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "UPDATE account_api_keys SET revoked_at = ? WHERE key_id = ?",
                (now, key_id),
            )
            _append_auth_audit(
                connection,
                action="api_key.revoked",
                actor_user_id=actor_id,
                target_user_id=row["user_id"],
                metadata={"key_id": key_id},
                now=now,
            )

    def authenticate(self, credential: str) -> tuple[UserRecord, ApiKeyRecord]:
        match = _KEY_PATTERN.fullmatch(credential)
        if match is None:
            raise InvalidApiKeyError("invalid API key")
        digest = hashlib.sha256(credential.encode("ascii")).hexdigest()
        # 同一個交易檢查停權、角色與撤銷狀態，再累計使用量，避免失敗也算用量。
        with self.database.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM account_api_keys WHERE key_id = ?",
                (match.group(1),),
            ).fetchone()
            if row is None or not hmac.compare_digest(
                row["credential_digest"], digest
            ):
                raise InvalidApiKeyError("invalid API key")
            now = datetime.now(timezone.utc)
            if row["revoked_at"] is not None:
                raise InvalidApiKeyError("invalid API key")
            if row["expires_at"] is not None:
                try:
                    expiry = datetime.fromisoformat(row["expires_at"])
                    if expiry.tzinfo is None or expiry <= now:
                        raise InvalidApiKeyError("invalid API key")
                except (TypeError, ValueError) as exc:
                    raise InvalidApiKeyError("invalid API key") from exc
            user_row = connection.execute(
                "SELECT * FROM users WHERE id = ?", (row["user_id"],)
            ).fetchone()
            if user_row is None:
                raise InvalidApiKeyError("invalid API key")
            user = _user_from_row(user_row)
            if (
                user.disabled
                or user.account_type is not AccountType.FORMAL
                or user.role.value != row["issued_role"]
                or user.token_version != row["issued_token_version"]
            ):
                raise InvalidApiKeyError("invalid API key")
            connection.execute(
                """
                UPDATE account_api_keys
                SET request_count = request_count + 1, last_used_at = ?
                WHERE key_id = ?
                """,
                (now.isoformat(), row["key_id"]),
            )
            updated = connection.execute(
                "SELECT * FROM account_api_keys WHERE key_id = ?",
                (row["key_id"],),
            ).fetchone()
        return user, _record(updated)

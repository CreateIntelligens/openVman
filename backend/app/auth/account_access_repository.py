"""Manage explicit read grants, account defaults, and ASR provider preferences."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from ._repository_base import RepositoryError, now_iso
from .database import AuthDatabase
from .models import (
    AccountDefaultsRecord,
    AccountType,
    ResourceGrantRecord,
    ResourceType,
)
from .policy import ensure_can_manage_account
from .repositories import (
    InvalidResourceGrantError,
    UserNotFoundError,
    _append_auth_audit,
    _defaults_from_row,
    _grant_from_row,
    _normalize_account_access,
    _persist_account_access,
    _user_from_row,
)


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
        defaults: tuple[str, ...],
        admin_portal_access: bool = False,
    ) -> tuple[tuple[ResourceGrantRecord, ...], AccountDefaultsRecord]:
        normalized_grants, normalized_defaults = _normalize_account_access(
            grants,
            defaults,
        )
        now = now_iso()
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

            _persist_account_access(
                connection,
                user_id=user_id,
                granted_by=granted_by,
                normalized_grants=normalized_grants,
                normalized_defaults=normalized_defaults,
                now=now,
                clear_existing=True,
            )
            connection.execute(
                """
                UPDATE users
                SET admin_portal_access = ?,
                    token_version = token_version + CASE
                        WHEN admin_portal_access != ? THEN 1 ELSE 0 END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    int(admin_portal_access),
                    int(admin_portal_access),
                    now,
                    user_id,
                ),
            )
            _append_auth_audit(
                connection,
                action="account_access_updated",
                actor_user_id=granted_by,
                target_user_id=user_id,
                metadata={"admin_portal_access": admin_portal_access},
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

    def get_asr_provider(self, user_id: str) -> str:
        """Return this account's ASR choice, or "" when it never picked one.

        沒有 account_defaults 資料列的帳號（例如還沒設過預設）回空字串，
        跟「選過但清空」的語意一致：都沿用全站設定。
        """
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT asr_provider FROM account_defaults WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return str(row["asr_provider"]) if row is not None else ""

    def set_asr_provider(self, user_id: str, provider: str) -> None:
        """Store this account's ASR choice; "" clears it.

        帳號可能還沒有 account_defaults 資料列，所以用 upsert；其餘欄位留白
        由既有的預設流程填。
        """
        with self.database.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO account_defaults(
                    user_id, project_id, character_id,
                    voice_provider, voice_id, asr_provider
                )
                VALUES (?, '', '', '', '', ?)
                ON CONFLICT(user_id) DO UPDATE SET asr_provider = excluded.asr_provider
                """,
                (user_id, provider),
            )

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

"""Temporary account batches, credentials, and their grant persistence.

從 repositories.py 搬出來的，行為未改。共用的 row 轉換與稽核 helper 仍留在
原檔並由此 import：它們同時服務正式帳號那幾個 repository，複製一份只會讓
兩邊各自漂移。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4

from ._repository_base import RepositoryError, now_iso
from .database import AuthDatabase
from .models import (
    AccountDefaultsRecord,
    AccountRole,
    AccountType,
    ResourceGrantRecord,
    ResourceType,
    TemporaryBatchRecord,
    TemporaryCredentialRecord,
    UserRecord,
)
from .policy import ensure_account_manager


class TemporaryCredentialNotFoundError(RepositoryError):
    pass


class TemporaryCredentialExpiredError(RepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class TemporaryCredentialCreate:
    locator: str
    password_hash: str
    password_ciphertext: str | None = field(default=None, repr=False)


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


# 共用 helper 與錯誤型別仍住在 repositories.py：它們同時服務正式帳號那幾個
# repository。延後到函式外的模組層 import 會造成循環（repositories 也要
# re-export 這個模組的 class），所以放在檔案尾端由 repositories 注入不可行，
# 改為在此直接引用——Python 只在第一次使用時解析，循環在 import 時不會觸發。
from .repositories import (
    InvalidResourceGrantError,
    UserNotFoundError,
    _append_auth_audit,
    _as_utc,
    _defaults_from_row,
    _ensure_grants_within_granter_scope,
    _grant_from_row,
    _normalize_account_access,
    _persist_account_access,
    _user_from_row,
    normalize_username,
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
        password_ciphertext=row["password_ciphertext"],
    )


def _ensure_batch_manageable(
    connection: sqlite3.Connection,
    *,
    actor: UserRecord,
    batch_id: str,
) -> None:
    """Only ROOT or the batch's creator may revoke it or toggle portal access.

    跟 ensure_can_manage_account 一樣只放行直屬：admin 動得了自己發的批次，
    動不了 ROOT 或別的 admin 發的。管不到的批次一律當不存在，不洩漏其存在。
    """
    ensure_account_manager(actor)
    row = connection.execute(
        "SELECT created_by FROM temporary_account_batches WHERE id = ?",
        (batch_id,),
    ).fetchone()
    if row is None or (
        actor.role is not AccountRole.ROOT and row["created_by"] != actor.id
    ):
        raise TemporaryCredentialNotFoundError("temporary batch does not exist")


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
        admin_portal_access: bool = False,
    ) -> TemporaryBatch:
        if len(credentials) != 5:
            raise ValueError("a temporary batch must contain exactly five credentials")
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")

        normalized_grants, normalized_defaults = _normalize_account_access(
            grants,
            defaults,
        )

        locators = [credential.locator for credential in credentials]
        if len(set(locators)) != len(credentials) or any(
            not value for value in locators
        ):
            raise ValueError("temporary credential locators must be unique")

        batch_id = f"tmpbatch_{uuid4().hex}"
        now = now_iso()
        try:
            with self.database.transaction(write=True) as connection:
                creator = connection.execute(
                    "SELECT * FROM users WHERE id = ?",
                    (created_by,),
                ).fetchone()
                if creator is None:
                    raise UserNotFoundError("administrator account does not exist")
                ensure_account_manager(_user_from_row(creator))
                _ensure_grants_within_granter_scope(
                    connection,
                    granted_by=created_by,
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
                            created_at, updated_at, created_by,
                            admin_portal_access
                        ) VALUES (?, ?, ?, ?, 'user', 'temporary', 0, 0, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            username,
                            normalize_username(username),
                            credential.password_hash,
                            now,
                            now,
                            created_by,
                            int(admin_portal_access),
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO temporary_credentials(
                            user_id, batch_id, code_locator, first_used_at,
                            expires_at, duration_seconds, password_ciphertext
                        ) VALUES (?, ?, ?, NULL, NULL, ?, ?)
                        """,
                        (
                            user_id,
                            batch_id,
                            credential.locator,
                            duration_seconds,
                            credential.password_ciphertext,
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
                    metadata={
                        "account_count": len(credentials),
                        "admin_portal_access": admin_portal_access,
                        "batch_id": batch_id,
                    },
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
                       temporary_credentials.duration_seconds,
                       temporary_credentials.password_ciphertext
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
                       temporary_credentials.duration_seconds,
                       temporary_credentials.password_ciphertext
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
                           temporary_credentials.duration_seconds,
                           temporary_credentials.password_ciphertext
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
                       temporary_credentials.duration_seconds,
                       temporary_credentials.password_ciphertext
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

    def list_batches(
        self,
        *,
        visible_to: str | None = None,
    ) -> list[TemporaryBatch]:
        """List batches; ``visible_to`` narrows to an administrator's subtree.

        臨時批次跟正式帳號走同一條可見規則：admin 只看得到自己和自己委派
        出去的下屬所建的批次。不過濾的話，受限 admin 會看到 ROOT 發出的
        每一批密碼。
        """
        if visible_to is None:
            query = """
                SELECT id FROM temporary_account_batches
                ORDER BY created_at DESC, id DESC
            """
            params: tuple[object, ...] = ()
        else:
            query = """
                WITH RECURSIVE subtree(id) AS (
                    SELECT id FROM users WHERE id = ?
                    UNION
                    SELECT users.id FROM users
                    JOIN subtree ON users.created_by = subtree.id
                )
                SELECT batches.id FROM temporary_account_batches AS batches
                JOIN subtree ON batches.created_by = subtree.id
                ORDER BY batches.created_at DESC, batches.id DESC
            """
            params = (visible_to,)
        with self.database.transaction() as connection:
            rows = connection.execute(query, params).fetchall()
        batches = [self.get_batch(row["id"]) for row in rows]
        return [batch for batch in batches if batch is not None]

    def set_admin_portal_access(
        self,
        batch_id: str,
        *,
        actor_id: str,
        enabled: bool,
    ) -> TemporaryBatch:
        now = now_iso()
        with self.database.transaction(write=True) as connection:
            actor = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (actor_id,),
            ).fetchone()
            if actor is None:
                raise UserNotFoundError("administrator account does not exist")
            _ensure_batch_manageable(
                connection, actor=_user_from_row(actor), batch_id=batch_id,
            )
            connection.execute(
                """
                UPDATE users
                SET admin_portal_access = ?,
                    token_version = token_version + CASE
                        WHEN admin_portal_access != ? THEN 1 ELSE 0 END,
                    updated_at = ?
                WHERE id IN (
                    SELECT user_id FROM temporary_credentials WHERE batch_id = ?
                )
                """,
                (int(enabled), int(enabled), now, batch_id),
            )
            _append_auth_audit(
                connection,
                action="temporary_batch_admin_portal_access_updated",
                actor_user_id=actor_id,
                target_user_id=None,
                metadata={
                    "admin_portal_access": enabled,
                    "batch_id": batch_id,
                },
                now=now,
            )
        batch = self.get_batch(batch_id)
        if batch is None:
            raise RepositoryError("updated temporary batch could not be reloaded")
        return batch

    def revoke_batch(
        self,
        batch_id: str,
        *,
        actor_id: str,
    ) -> TemporaryBatch:
        now = now_iso()
        with self.database.transaction(write=True) as connection:
            actor = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (actor_id,),
            ).fetchone()
            if actor is None:
                raise UserNotFoundError("administrator account does not exist")
            _ensure_batch_manageable(
                connection, actor=_user_from_row(actor), batch_id=batch_id,
            )
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

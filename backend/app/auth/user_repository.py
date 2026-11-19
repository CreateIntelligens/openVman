"""User account management and lifecycle repository."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from uuid import uuid4

from ._account_access_rules import (
    _normalize_account_access,
    _persist_account_access,
    ensure_vendor_target_within_scope,
    vendor_target_within_scope,
)
from ._account_records import (
    _ADMIN_OR_ABOVE_PLACEHOLDERS,
    _append_auth_audit,
    _display_username,
    _load_actor_and_target,
    _user_from_row,
    normalize_username,
)
from ._admin_scope_rules import _inherit_admin_scope, _load_admin_scope
from ._repository_base import now_iso
from .database import AuthDatabase
from .models import (
    ADMIN_OR_ABOVE_VALUES,
    ROOT_USERNAME,
    AccountRole,
    AccountType,
    ProjectWritePermissions,
    ResourceType,
    UserRecord,
    is_at_least_admin,
)
from .policy import (
    AccountPolicyError,
    can_manage_vendor_accounts,
    ensure_account_manager,
    ensure_can_change_role,
    ensure_can_create_role,
    ensure_can_manage_account,
    ensure_can_reset_password,
)
from .repository_errors import (
    AccountEnabledError,
    AdminAlreadyExistsError,
    InvalidResourceGrantError,
    LastAdminError,
    OwnedResourcesError,
    RepositoryError,
    SelfProtectionError,
    UserNotFoundError,
    UsernameConflictError,
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
        admin_portal_access: bool = False,
        kiosk: bool = False,
        ai_cleanup_access: bool = False,
        vendor_name: str | None = None,
        project_permissions: Mapping[str, ProjectWritePermissions] | None = None,
    ) -> UserRecord:
        if role is AccountRole.ROOT:
            raise AccountPolicyError("ROOT accounts cannot be created")
        vendor_name = (vendor_name or "").strip() or None
        if vendor_name and (role is not AccountRole.USER or account_type is not AccountType.FORMAL):
            raise AccountPolicyError("vendor affiliation requires a formal user")
        if vendor_name and created_by is None:
            raise AccountPolicyError("vendor account management access required")
        if (grants is None) != (defaults is None):
            raise InvalidResourceGrantError(
                "account grants and defaults must be provided together"
            )
        normalized_access = (
            _normalize_account_access(grants, defaults)
            if grants is not None and defaults is not None
            else None
        )
        # 建立 admin 時可一併給資源，但這只有 ROOT 做得到；建立者是誰要
        # 進到交易裡才查得到，所以實際檢查延後到下面的 created_by 區塊。

        user_id = f"usr_{uuid4().hex}"
        display_username = _display_username(username)
        normalized_username = normalize_username(username)
        now = now_iso()

        try:
            with self.database.transaction(write=True) as connection:
                if created_by is not None:
                    creator = connection.execute(
                        "SELECT * FROM users WHERE id = ?",
                        (created_by,),
                    ).fetchone()
                    if creator is None:
                        raise UserNotFoundError("creator account does not exist")
                    creator_record = _user_from_row(creator)
                    ensure_can_create_role(creator_record, role)
                    if vendor_name and not can_manage_vendor_accounts(creator_record):
                        raise AccountPolicyError("vendor account management access required")
                    if (
                        normalized_access is not None
                        and is_at_least_admin(role)
                        and creator_record.role is not AccountRole.ROOT
                    ):
                        raise InvalidResourceGrantError(
                            "only ROOT can set administrator resources"
                        )
                connection.execute(
                    """
                    INSERT INTO users(
                        id, username, username_normalized, password_hash, role,
                        account_type, disabled, token_version, created_at,
                        updated_at, created_by, admin_portal_access, kiosk,
                        ai_cleanup_access, vendor_name
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?)
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
                        int(admin_portal_access),
                        int(kiosk),
                        int(ai_cleanup_access),
                        vendor_name,
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
                        project_permissions=project_permissions,
                        legacy_project_edit=admin_portal_access,
                    )
                if is_at_least_admin(role) and created_by is not None:
                    # 受限 admin 開出來的 admin 必須在同一筆交易裡繼承上層的
                    # 上限。少了這段，新帳號沒有 scope 列就等於不設限，受限
                    # admin 只要開一個下屬就能取回自己拿不到的資源。
                    _inherit_admin_scope(
                        connection,
                        admin_user_id=user_id,
                        created_by=created_by,
                        now=now,
                    )
                if created_by is not None:
                    _append_auth_audit(
                        connection,
                        action="account_created",
                        actor_user_id=created_by,
                        target_user_id=user_id,
                        metadata={
                            "account_type": account_type.value,
                            "admin_portal_access": admin_portal_access,
                            "kiosk": kiosk,
                            "ai_cleanup_access": ai_cleanup_access,
                            "role": role.value,
                            "vendor_name": vendor_name,
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
        if normalized_username != ROOT_USERNAME:
            raise ValueError(f"ROOT username must be {ROOT_USERNAME}")
        now = now_iso()

        try:
            with self.database.transaction(write=True) as connection:
                existing = connection.execute(
                    "SELECT id, username_normalized FROM users WHERE role = 'root' LIMIT 1"
                ).fetchone()
                if existing is not None:
                    raise AdminAlreadyExistsError("ROOT already exists")
                conflicting = connection.execute(
                    "SELECT 1 FROM users WHERE username_normalized = ?",
                    (ROOT_USERNAME,),
                ).fetchone()
                if conflicting is not None:
                    raise UsernameConflictError(f"{ROOT_USERNAME} already exists")
                connection.execute(
                    """
                    INSERT INTO users(
                        id, username, username_normalized, password_hash, role,
                        account_type, disabled, token_version, created_at,
                        updated_at, created_by, admin_portal_access
                    ) VALUES (?, ?, ?, ?, 'root', 'formal', 0, 0, ?, ?, NULL, 0)
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

    def list_visible_subtree(
        self,
        actor_id: str,
        *,
        account_type: AccountType | None = None,
        include_vendors: bool = False,
    ) -> list[UserRecord]:
        """List the accounts an administrator may see, plus their own row.

        可見 ≠ 可管理：整棵委派子樹都看得到，但只有直屬下一層編輯得了
        （ensure_can_manage_account 比對 created_by）。沒有遞迴的話，上層
        就看不到自己委派出去的分支底下發生什麼事。
        """
        query = """
            WITH RECURSIVE subtree(id) AS (
                SELECT id FROM users WHERE id = ?
                UNION
                SELECT users.id FROM users
                JOIN subtree ON users.created_by = subtree.id
            )
            SELECT users.* FROM users
            WHERE (users.id IN (SELECT id FROM subtree)
                OR (? AND users.role = 'user' AND users.account_type = 'formal'
                    AND users.vendor_name IS NOT NULL))
        """
        params: list[object] = [actor_id, include_vendors]
        if account_type is not None:
            query += " AND users.account_type = ?"
            params.append(account_type.value)
        query += " ORDER BY users.username_normalized, users.id"
        with self.database.transaction() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            if include_vendors:
                scope = _load_admin_scope(connection, actor_id)
                rows = [
                    row for row in rows
                    if row["vendor_name"] is None
                    or vendor_target_within_scope(connection, scope, row["id"])
                ]
        return [_user_from_row(row) for row in rows]

    def has_admin(self) -> bool:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT 1 FROM users "
                f"WHERE role IN ({_ADMIN_OR_ABOVE_PLACEHOLDERS}) LIMIT 1",
                ADMIN_OR_ABOVE_VALUES,
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
            ensure_can_manage_account(actor, target, cross_creator_vendor=True)
            ensure_vendor_target_within_scope(connection, actor, target)
            if disabled and actor_id == user_id:
                raise SelfProtectionError("administrator cannot disable itself")
            if (
                disabled
                and is_at_least_admin(target.role)
                and not target.disabled
            ):
                enabled_admins = connection.execute(
                    "SELECT COUNT(*) FROM users "
                    f"WHERE role IN ({_ADMIN_OR_ABOVE_PLACEHOLDERS}) "
                    "AND disabled = 0",
                    ADMIN_OR_ABOVE_VALUES,
                ).fetchone()[0]
                if enabled_admins <= 1:
                    raise LastAdminError(
                        "cannot disable the final enabled administrator"
                    )
            if target.disabled != disabled:
                now = now_iso()
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

    def set_vendor_affiliation(
        self, *, actor_id: str, user_id: str, vendor_name: str | None,
    ) -> UserRecord:
        vendor_name = (vendor_name or "").strip() or None
        with self.database.transaction(write=True) as connection:
            actor, target = _load_actor_and_target(connection, actor_id, user_id)
            ensure_account_manager(actor)
            if actor.role is not AccountRole.ROOT:
                raise AccountPolicyError("only ROOT can change vendor affiliation")
            if target.role is not AccountRole.USER or target.account_type is not AccountType.FORMAL:
                raise AccountPolicyError("vendor affiliation requires a formal user")
            if target.vendor_name == vendor_name:
                return target
            now = now_iso()
            connection.execute(
                """
                UPDATE users SET vendor_name = ?, updated_at = ?,
                    token_version = token_version + 1 WHERE id = ?
                """,
                (vendor_name, now, user_id),
            )
            # 換了廠商，舊的帳號金鑰是照原歸屬代發的；token_version 只讓登入失效，金鑰要另外撤銷。
            connection.execute(
                "UPDATE account_api_keys SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (now, user_id),
            )
            _append_auth_audit(
                connection,
                action="account_vendor_updated",
                actor_user_id=actor_id,
                target_user_id=user_id,
                metadata={"vendor_name": vendor_name},
                now=now,
            )
        return self._reload_user(user_id)

    def set_account_management_access(
        self, *, actor_id: str, user_id: str, enabled: bool,
    ) -> UserRecord:
        with self.database.transaction(write=True) as connection:
            actor, target = _load_actor_and_target(connection, actor_id, user_id)
            ensure_account_manager(actor)
            if actor.role is not AccountRole.ROOT:
                raise AccountPolicyError("only ROOT can grant account management access")
            if target.role is not AccountRole.ADMIN or target.account_type is not AccountType.FORMAL:
                raise AccountPolicyError("account management access requires a formal administrator")
            if target.account_management_access == enabled:
                return target
            now = now_iso()
            connection.execute(
                "UPDATE users SET account_management_access = ?, updated_at = ? WHERE id = ?",
                (enabled, now, user_id),
            )
            _append_auth_audit(
                connection,
                action="account_management_access_updated",
                actor_user_id=actor_id,
                target_user_id=user_id,
                metadata={"enabled": enabled},
                now=now,
            )
        return self._reload_user(user_id)

    def _reload_user(self, user_id: str) -> UserRecord:
        user = self.get_by_id(user_id)
        if user is None:
            raise RepositoryError("updated account could not be reloaded")
        return user

    def record_login(self, user_id: str, *, now: datetime) -> None:
        """Stamp a successful sign-in without touching updated_at or the audit log.

        updated_at 代表「帳號被改過」，登入不算；每次登入都寫稽核會把表灌爆，
        而後台只需要最後一次的時間來判斷帳號還有沒有人用。
        """
        with self.database.transaction(write=True) as connection:
            connection.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (now.isoformat(), user_id),
            )

    def revoke_sessions(
        self,
        user_id: str,
        *,
        actor_id: str,
    ) -> UserRecord:
        with self.database.transaction(write=True) as connection:
            actor, target = _load_actor_and_target(connection, actor_id, user_id)
            ensure_can_manage_account(actor, target)
            ensure_vendor_target_within_scope(connection, actor, target)
            now = now_iso()
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
            ensure_vendor_target_within_scope(connection, actor, target)
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

            now = now_iso()
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
        admin_portal_access: bool = False,
        kiosk: bool | None = None,
        ai_cleanup_access: bool | None = None,
        project_permissions: Mapping[str, ProjectWritePermissions] | None = None,
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
            # 升為 admin 時一併給資源是允許的；change_role 本來就只有 ROOT
            # 能呼叫（ensure_can_change_role），不需要再擋一次。

            now = now_iso()
            if role is AccountRole.USER:
                if normalized_access is None:
                    raise InvalidResourceGrantError(
                        "demoting an administrator requires grants and defaults"
                    )
                normalized_grants, normalized_defaults = normalized_access
                _persist_account_access(
                    connection,
                    user_id=user_id,
                    granted_by=actor_id,
                    normalized_grants=normalized_grants,
                    normalized_defaults=normalized_defaults,
                    now=now,
                    clear_existing=True,
                    project_permissions=project_permissions,
                    legacy_project_edit=admin_portal_access,
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
                SET role = ?, admin_portal_access = ?, account_management_access = 0,
                    token_version = token_version + 1, updated_at = ?
                WHERE id = ?
                """,
                (
                    role.value,
                    int(admin_portal_access) if role is AccountRole.USER else 0,
                    now,
                    user_id,
                ),
            )
            if kiosk is not None:
                connection.execute(
                    "UPDATE users SET kiosk = ? WHERE id = ?",
                    (int(kiosk), user_id),
                )
            if ai_cleanup_access is not None:
                connection.execute(
                    "UPDATE users SET ai_cleanup_access = ? WHERE id = ?",
                    (int(ai_cleanup_access), user_id),
                )
            _append_auth_audit(
                connection,
                action="account_role_changed",
                actor_user_id=actor_id,
                target_user_id=user_id,
                metadata={
                    "admin_portal_access": (
                        admin_portal_access if role is AccountRole.USER else True
                    ),
                    "from_role": target.role.value,
                    "to_role": role.value,
                },
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
            ensure_vendor_target_within_scope(connection, actor, target)

            now = now_iso()
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
                root.username_normalized != ROOT_USERNAME
                or root.account_type is not AccountType.FORMAL
            ):
                raise RepositoryError("ROOT identity is invalid")
            now = now_iso()
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
            now = now_iso()
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


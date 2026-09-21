"""ROOT-assigned resource ceilings for administrators.

從 repositories.py 搬出來的，行為未改。scope 的計算與級聯（_load_admin_scope、
_narrow_subordinate_scopes、_revoke_grants_outside_scope）仍留在原檔：建立帳號
那條路也要用它們，搬過來會反向依賴。
"""

from __future__ import annotations

from collections.abc import Iterable

from ._repository_base import now_iso
from .database import AuthDatabase
from .models import AccountRole, AdminScope, ResourceType
from .policy import ensure_can_manage_account

# 這些留在 repositories.py：建立帳號那條路也要用，搬過來會反向依賴。
from .repositories import (
    InvalidResourceGrantError,
    UserNotFoundError,
    _append_auth_audit,
    _load_admin_scope,
    _narrow_subordinate_scopes,
    _revoke_grants_outside_scope,
    _user_from_row,
)


class AdminScopeRepository:
    """Manage the resource ceiling ROOT assigns to an administrator.

    An administrator with no scope row keeps the historical unrestricted
    access, so existing deployments are unaffected until ROOT sets a ceiling.
    """

    def __init__(self, database: AuthDatabase) -> None:
        self.database = database

    def get(self, admin_user_id: str) -> AdminScope:
        with self.database.transaction() as connection:
            return _load_admin_scope(connection, admin_user_id)

    def replace(
        self,
        *,
        admin_user_id: str,
        updated_by: str,
        scoped: bool,
        resources: Iterable[tuple[ResourceType, str]],
    ) -> AdminScope:
        """Set (or clear) an administrator's ceiling. ROOT only."""
        normalized = tuple(
            sorted(
                {
                    (item[0], item[1].strip())
                    for item in resources
                    if item[1].strip()
                },
                key=lambda item: (item[0].value, item[1]),
            )
        )
        now = now_iso()
        with self.database.transaction(write=True) as connection:
            actor = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (updated_by,),
            ).fetchone()
            if actor is None:
                raise UserNotFoundError("administrator account does not exist")
            actor_record = _user_from_row(actor)

            target = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (admin_user_id,),
            ).fetchone()
            if target is None:
                raise UserNotFoundError("account does not exist")
            target_record = _user_from_row(target)
            if target_record.role is not AccountRole.ADMIN:
                raise InvalidResourceGrantError(
                    "resource scopes apply to administrator accounts only"
                )
            if actor_record.role is not AccountRole.ROOT:
                ensure_can_manage_account(actor_record, target_record)
                # 委派出去的上限只能是自己的子集，而且不得是「不設限」——否則
                # 受限 admin 可以開一個 unscoped 的下屬,再透過他取回全部資源。
                actor_scope = _load_admin_scope(connection, actor_record.id)
                if actor_scope.scoped:
                    if not scoped:
                        raise InvalidResourceGrantError(
                            "a scoped administrator cannot grant unrestricted scope"
                        )
                    outside = [
                        f"{resource_type.value}/{resource_id}"
                        for resource_type, resource_id in normalized
                        if not actor_scope.allows(resource_type, resource_id)
                    ]
                    if outside:
                        raise InvalidResourceGrantError(
                            "resources outside your own scope: "
                            + ", ".join(sorted(outside))
                        )

            for resource_type, resource_id in normalized:
                exists = connection.execute(
                    """
                    SELECT 1 FROM resources
                    WHERE resource_type = ? AND resource_id = ?
                    """,
                    (resource_type.value, resource_id),
                ).fetchone()
                if exists is None:
                    raise InvalidResourceGrantError(
                        "resource is not registered: "
                        f"{resource_type.value}/{resource_id}"
                    )

            connection.execute(
                "DELETE FROM admin_resource_scopes WHERE admin_user_id = ?",
                (admin_user_id,),
            )
            if scoped and normalized:
                connection.executemany(
                    """
                    INSERT INTO admin_resource_scopes(
                        admin_user_id, resource_type, resource_id,
                        granted_by, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            admin_user_id,
                            resource_type.value,
                            resource_id,
                            updated_by,
                            now,
                        )
                        for resource_type, resource_id in normalized
                    ],
                )

            if scoped:
                connection.execute(
                    """
                    INSERT INTO admin_scope_state(
                        admin_user_id, scoped, updated_by, updated_at
                    ) VALUES (?, 1, ?, ?)
                    ON CONFLICT(admin_user_id) DO UPDATE SET
                        scoped = 1, updated_by = excluded.updated_by,
                        updated_at = excluded.updated_at
                    """,
                    (admin_user_id, updated_by, now),
                )
            else:
                connection.execute(
                    "DELETE FROM admin_scope_state WHERE admin_user_id = ?",
                    (admin_user_id,),
                )

            # 範圍縮小後，這個 admin 先前發出去、如今已超出自己上限的授權
            # 必須跟著失效，否則收斂只擋新授權、擋不住既有的。
            revoked = 0
            if scoped:
                revoked = _revoke_grants_outside_scope(
                    connection,
                    admin_user_id=admin_user_id,
                    allowed=normalized,
                )
                _narrow_subordinate_scopes(
                    connection,
                    admin_user_id=admin_user_id,
                    allowed=normalized,
                    updated_by=updated_by,
                    now=now,
                )

            _append_auth_audit(
                connection,
                action="admin_scope_updated",
                actor_user_id=updated_by,
                target_user_id=admin_user_id,
                metadata={
                    "scoped": scoped,
                    "resource_count": len(normalized) if scoped else 0,
                    "revoked_grants": revoked,
                },
                now=now,
            )

        return self.get(admin_user_id)

    def list_scoped_admin_ids(self) -> frozenset[str]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT admin_user_id FROM admin_scope_state WHERE scoped = 1"
            ).fetchall()
        return frozenset(row["admin_user_id"] for row in rows)

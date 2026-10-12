"""Administrator resource ceilings and the cascade that enforces them.

建立帳號、授權與縮權三條路都要讀上限，撤銷授權時又得連帶修正預設值，
所以 scope 計算、級聯撤權與預設值改指向放在同一個模組。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence

from ._account_records import _ADMIN_OR_ABOVE_PLACEHOLDERS
from .models import ADMIN_OR_ABOVE_VALUES, AdminScope, ResourceType


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

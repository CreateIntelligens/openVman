"""Schema 26 retires the built-in Frieren (qqman) and VRM 3D (vrm-sample) mascots."""

from __future__ import annotations

from pathlib import Path

from app.auth.database import AuthDatabase
from app.auth.models import AccountRole, ResourceType
from app.auth.resource_repository import ResourceRepository
from app.auth.user_repository import UserRepository

RETIRED = ("qqman", "vrm-sample")


def _upgrade_from_25(tmp_path: Path):
    database = AuthDatabase(tmp_path / "accounts.db")
    database.initialize()
    resources = ResourceRepository(database)
    users = UserRepository(database)
    for mascot_id in (*RETIRED, "haru-live2d"):
        resources.upsert_system_resource(
            resource_type=ResourceType.AVATAR_MASCOT, resource_id=mascot_id
        )
    user = users.create(username="kiosk", password_hash="hash", role=AccountRole.USER)
    keeper = users.create(username="keeper", password_hash="hash", role=AccountRole.USER)
    # 模擬升級前：帳號有這些 VRM 的授權、預設指到要拿掉的那個，遷移紀錄停在 25。
    with database.transaction(write=True) as connection:
        for mascot_id in ("qqman", "haru-live2d"):
            connection.execute(
                """
                INSERT INTO resource_grants (
                    grantee_user_id, resource_type, resource_id, granted_by, created_at
                ) VALUES (?, 'avatar_mascot', ?, NULL, '2026-10-22T00:00:00+00:00')
                """,
                (user.id, mascot_id),
            )
        for account, mascot_id in ((user, "qqman"), (keeper, "haru-live2d")):
            connection.execute(
                """
                INSERT INTO account_defaults(
                    user_id, project_id, character_id, voice_provider, voice_id, mascot_id
                ) VALUES (?, 'proj', 'char', 'edge-tts', 'voice', ?)
                ON CONFLICT(user_id) DO UPDATE SET mascot_id = excluded.mascot_id
                """,
                (account.id, mascot_id),
            )
        connection.execute("DELETE FROM schema_migrations WHERE version = 26")
    database.initialize()
    return database, user, keeper


def test_retired_vrm_resources_and_their_grants_are_removed(tmp_path: Path):
    database, user, _keeper = _upgrade_from_25(tmp_path)

    with database.transaction() as connection:
        mascots = {
            row["resource_id"]
            for row in connection.execute(
                "SELECT resource_id FROM resources WHERE resource_type = 'avatar_mascot'"
            )
        }
        grants = {
            row["resource_id"]
            for row in connection.execute(
                "SELECT resource_id FROM resource_grants WHERE grantee_user_id = ?",
                (user.id,),
            )
        }

    assert mascots == {"haru-live2d"}
    assert grants == {"haru-live2d"}


def test_defaults_pointing_at_a_retired_vrm_are_cleared(tmp_path: Path):
    database, user, keeper = _upgrade_from_25(tmp_path)

    with database.transaction() as connection:
        defaults = {
            row["user_id"]: row["mascot_id"]
            for row in connection.execute("SELECT user_id, mascot_id FROM account_defaults")
        }
        applied = [
            row["version"]
            for row in connection.execute("SELECT version FROM schema_migrations")
        ]

    assert defaults[user.id] == ""
    assert defaults[keeper.id] == "haru-live2d"
    assert applied.count(26) == 1

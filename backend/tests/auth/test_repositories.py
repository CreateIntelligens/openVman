"""SQLite auth repository contract tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.auth.database import AuthDatabase
from app.auth.models import AccountRole, ResourceType, ResourceVisibility
from app.auth.repositories import (
    InvalidResourceGrantError,
    ResourceConflictError,
    ResourceRepository,
    UserRepository,
    UsernameConflictError,
    _normalize_account_access,
)


@pytest.fixture()
def repositories(
    tmp_path: Path,
) -> tuple[AuthDatabase, UserRepository, ResourceRepository]:
    database = AuthDatabase(tmp_path / "auth" / "accounts.db")
    database.initialize()
    return database, UserRepository(database), ResourceRepository(database)


def test_migration_is_idempotent_and_enables_sqlite_safety_pragmas(tmp_path: Path):
    database = AuthDatabase(tmp_path / "accounts.db")
    database.initialize()
    database.initialize()

    with database.transaction() as connection:
        migrations = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    applied = [row["version"] for row in migrations]
    # 只驗證遷移不重複、且按序套用；確切版本號會隨新遷移增加。
    assert applied == sorted(set(applied))
    assert applied[:4] == [1, 2, 3, 4]
    assert journal_mode == "wal"
    assert foreign_keys == 1
    assert busy_timeout == 5000


def test_temporary_migration_recovers_when_column_already_exists(tmp_path: Path):
    database = AuthDatabase(tmp_path / "accounts.db")
    database.initialize()
    with database.transaction(write=True) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 2")

    database.initialize()

    with database.transaction() as connection:
        migrations = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(users)")
        }
    applied = [row["version"] for row in migrations]
    # 只驗證遷移不重複、且按序套用；確切版本號會隨新遷移增加。
    assert applied == sorted(set(applied))
    assert applied[:4] == [1, 2, 3, 4]
    assert "account_type" in columns


def test_normalized_usernames_are_unique(repositories):
    _, users, _ = repositories
    users.create(
        username="Ａlice",
        password_hash="hash",
        role=AccountRole.USER,
    )

    with pytest.raises(UsernameConflictError):
        users.create(
            username=" alice ",
            password_hash="hash",
            role=AccountRole.USER,
        )


def test_concurrent_reads_and_writes_complete_without_lock_errors(repositories):
    _, users, _ = repositories

    def _create(index: int) -> str:
        return users.create(
            username=f"user-{index}",
            password_hash="hash",
            role=AccountRole.USER,
        ).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        user_ids = list(executor.map(_create, range(24)))
        loaded = list(executor.map(users.get_by_id, user_ids))

    assert len({user.id for user in loaded if user is not None}) == 24


def test_disabled_token_version_and_ownership_counts_persist(repositories):
    database, users, resources = repositories
    # 撤銷工作階段需要一個具權限的 actor，政策檢查與 audit 才會執行。
    root = users.create_root(username="ai360", password_hash="hash")
    user = users.create(
        username="owner",
        password_hash="hash",
        role=AccountRole.USER,
    )
    users.set_disabled_guarded(actor_id=root.id, user_id=user.id, disabled=True)
    users.revoke_sessions(user.id, actor_id=root.id)
    resources.register(
        resource_type=ResourceType.PROJECT,
        resource_id="project-a",
        owner_user_id=user.id,
        visibility=ResourceVisibility.PRIVATE,
    )
    resources.register(
        resource_type=ResourceType.CUSTOM_VOICE,
        resource_id="voice-a",
        owner_user_id=user.id,
        visibility=ResourceVisibility.PRIVATE,
    )

    reloaded_users = UserRepository(database)
    reloaded_resources = ResourceRepository(database)
    reloaded = reloaded_users.get_by_id(user.id)

    assert reloaded is not None
    assert reloaded.disabled is True
    # 停用本身就會撤銷工作階段，再加上明確的 revoke_sessions 共兩次遞增。
    assert reloaded.token_version == 2
    assert reloaded_resources.count_private_by_owner(user.id) == {
        "custom_voice": 1,
        "project": 1,
    }
    assert [record.resource_id for record in resources.list_owned(user.id)] == [
        "voice-a",
        "project-a",
    ]


def test_resource_identity_conflict_is_deterministic(repositories):
    _, users, resources = repositories
    owner = users.create(
        username="owner",
        password_hash="hash",
        role=AccountRole.USER,
    )
    registration = {
        "resource_type": ResourceType.PROJECT,
        "resource_id": "same-id",
        "owner_user_id": owner.id,
        "visibility": ResourceVisibility.PRIVATE,
    }
    resources.register(**registration)

    with pytest.raises(ResourceConflictError, match="resource already registered"):
        resources.register(**registration)


def _access(*, character: str = "", mascot: str = ""):
    """Build a minimal grant/defaults pair with the required project+voice."""
    grants = [
        (ResourceType.PROJECT, "default"),
        (ResourceType.CUSTOM_VOICE, "hayley"),
    ]
    if character:
        grants.append((ResourceType.AVATAR_CHARACTER, character))
    if mascot:
        grants.append((ResourceType.AVATAR_MASCOT, mascot))
    return grants, ("default", character, "indextts", "hayley", mascot, "")


@pytest.mark.parametrize(
    ("character", "mascot"),
    [("0713", ""), ("", "qqman"), ("0713", "qqman")],
)
def test_stage_avatar_accepts_character_or_vrm(character: str, mascot: str):
    grants, defaults = _access(character=character, mascot=mascot)

    normalized_grants, normalized_defaults = _normalize_account_access(
        grants,
        defaults,
    )

    assert normalized_defaults[1] == character
    assert normalized_defaults[4] == mascot
    assert len(normalized_grants) == len(grants)


def test_stage_avatar_requires_at_least_one_of_character_or_vrm():
    grants, defaults = _access()

    with pytest.raises(InvalidResourceGrantError, match="character or VRM"):
        _normalize_account_access(grants, defaults)

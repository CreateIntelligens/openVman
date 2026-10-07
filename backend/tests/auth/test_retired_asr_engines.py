"""Engines removed from the code must not linger in grants or saved choices."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.auth.database import AuthDatabase
from app.auth.models import AccountRole, ResourceType
from app.auth.passwords import hash_password
from app.auth.repositories import (
    AccountAccessRepository,
    ResourceRepository,
    UserRepository,
)
from app.auth.settings_routes import get_my_asr_provider
from app.routes import admin as admin_routes

_NOW = "2026-09-01T00:00:00Z"


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    database = AuthDatabase(tmp_path / "auth" / "accounts.db")
    database.initialize()
    users = UserRepository(database)
    root = users.create_root(username="ai360", password_hash=hash_password("root-password"))
    admin = users.create(
        username="admin-user",
        password_hash=hash_password("admin-password"),
        role=AccountRole.ADMIN,
        created_by=root.id,
    )
    user = users.create(
        username="plain-user",
        password_hash=hash_password("user-password"),
        role=AccountRole.USER,
        created_by=root.id,
    )
    runtime = SimpleNamespace(
        resources=ResourceRepository(database),
        account_access=AccountAccessRepository(database),
    )
    monkeypatch.setattr(
        "app.auth.settings_routes.get_tts_config",
        lambda: SimpleNamespace(asr_provider="breeze"),
    )
    return SimpleNamespace(
        database=database, runtime=runtime, root=root, admin=admin, user=user,
    )


def _seed_retired_engine(env) -> None:
    """模擬升級前的資料庫：xiaomi 已註冊、授權給帳號、被設成偏好與 admin 範圍。"""
    env.runtime.resources.upsert_system_resource(
        resource_type=ResourceType.ASR_ENGINE, resource_id="xiaomi",
    )
    with env.database.transaction(write=True) as connection:
        for grantee in (env.user.id, env.admin.id):
            connection.execute(
                "INSERT INTO resource_grants VALUES (?, 'asr_engine', ?, ?, ?)",
                (grantee, "xiaomi", env.root.id, _NOW),
            )
        connection.execute(
            "INSERT INTO admin_resource_scopes VALUES (?, 'asr_engine', ?, ?, ?)",
            (env.admin.id, "xiaomi", env.root.id, _NOW),
        )
    env.runtime.account_access.set_asr_provider(env.user.id, "xiaomi")


def _count(env, table: str) -> int:
    with env.database.transaction() as connection:
        return connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE resource_id = 'xiaomi'"
        ).fetchone()[0]


def test_sync_drops_retired_engine_with_its_grants_and_choices(env):
    _seed_retired_engine(env)

    admin_routes.sync_asr_engines(env.runtime)

    registered = {
        record.resource_id
        for record in env.runtime.resources.list_by_type(ResourceType.ASR_ENGINE)
    }
    assert registered == set(admin_routes._ASR_ENGINE_LABELS)
    assert _count(env, "resource_grants") == 0
    assert _count(env, "admin_resource_scopes") == 0
    assert env.runtime.account_access.get_asr_provider(env.user.id) == ""


def test_choices_naming_live_engines_survive(env):
    env.runtime.account_access.set_asr_provider(env.user.id, "sensevoice")
    env.runtime.account_access.set_asr_provider(env.admin.id, "gemini-live")

    admin_routes.sync_asr_engines(env.runtime)

    assert env.runtime.account_access.get_asr_provider(env.user.id) == "sensevoice"
    assert env.runtime.account_access.get_asr_provider(env.admin.id) == "gemini-live"


def test_profile_reads_as_unset_after_cleanup(env):
    """清掉之後前台讀到的是「沒選過」，不會拿著一個已不存在的引擎去存而被 422。"""
    _seed_retired_engine(env)

    admin_routes.sync_asr_engines(env.runtime)
    profile = get_my_asr_provider(
        account=SimpleNamespace(user=env.user), runtime=env.runtime,
    )

    assert profile.value == ""
    assert profile.effective == "breeze"
    assert "xiaomi" not in profile.allowed

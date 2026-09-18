"""Operator-editable ASR provider setting: storage, validation, and fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.auth.database import AuthDatabase
from app.auth.models import AccountRole
from app.auth.passwords import hash_password
from app.auth.repositories import UserRepository
from app.auth.settings_repository import (
    ASR_PROVIDER_KEY,
    InvalidSettingValueError,
    SystemSettingsRepository,
    UnknownSettingError,
)


@pytest.fixture()
def env(tmp_path: Path):
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
    return {
        "settings": SystemSettingsRepository(database),
        "database": database,
        "root": root,
        "admin": admin,
    }


def test_no_override_reads_as_absent(env):
    """沒有紀錄要回 None，呼叫端才知道該用環境變數的預設。"""
    assert env["settings"].get(ASR_PROVIDER_KEY) is None
    assert env["settings"].all() == {}


def test_set_then_get_round_trips(env):
    env["settings"].set(ASR_PROVIDER_KEY, "breeze", actor_id=env["root"].id)
    assert env["settings"].get(ASR_PROVIDER_KEY) == "breeze"


def test_set_overwrites_rather_than_duplicating(env):
    env["settings"].set(ASR_PROVIDER_KEY, "breeze", actor_id=env["root"].id)
    env["settings"].set(ASR_PROVIDER_KEY, "sensevoice", actor_id=env["root"].id)
    assert env["settings"].get(ASR_PROVIDER_KEY) == "sensevoice"
    assert env["settings"].all() == {ASR_PROVIDER_KEY: "sensevoice"}


def test_clear_restores_the_environment_default(env):
    env["settings"].set(ASR_PROVIDER_KEY, "breeze", actor_id=env["root"].id)
    env["settings"].clear(ASR_PROVIDER_KEY, actor_id=env["root"].id)
    assert env["settings"].get(ASR_PROVIDER_KEY) is None


def test_value_outside_the_allowed_set_is_refused(env):
    """打錯一個字母就整站沒有語音辨識，而且要到下次有人講話才發現。"""
    with pytest.raises(InvalidSettingValueError):
        env["settings"].set(ASR_PROVIDER_KEY, "sensevoic", actor_id=env["root"].id)
    assert env["settings"].get(ASR_PROVIDER_KEY) is None


def test_unknown_key_is_refused(env):
    with pytest.raises(UnknownSettingError):
        env["settings"].set("no_such_setting", "x", actor_id=env["root"].id)


def test_every_change_is_attributed_in_the_audit_log(env):
    """這些設定影響每個使用者，出事要查得到是誰在什麼時候動的。"""
    env["settings"].set(ASR_PROVIDER_KEY, "breeze", actor_id=env["root"].id)

    with env["database"].transaction() as connection:
        rows = connection.execute(
            "SELECT actor_user_id, metadata_json FROM auth_audit_events "
            "WHERE action = 'system_setting_updated'"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["actor_user_id"] == env["root"].id
    assert "breeze" in rows[0]["metadata_json"]


def test_clearing_is_audited_too(env):
    env["settings"].set(ASR_PROVIDER_KEY, "breeze", actor_id=env["root"].id)
    env["settings"].clear(ASR_PROVIDER_KEY, actor_id=env["admin"].id)

    with env["database"].transaction() as connection:
        rows = connection.execute(
            "SELECT actor_user_id FROM auth_audit_events "
            "WHERE action = 'system_setting_updated' ORDER BY created_at"
        ).fetchall()

    assert [row["actor_user_id"] for row in rows] == [env["root"].id, env["admin"].id]

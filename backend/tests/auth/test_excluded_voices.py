"""Voices excluded after registration must leave the grant lists."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app import system_resources
from app.auth.database import AuthDatabase
from app.auth.models import AccountRole, ResourceType
from app.auth.passwords import hash_password
from app.auth.resource_repository import ResourceRepository
from app.auth.user_repository import UserRepository

_NOW = "2026-09-02T00:00:00Z"


@pytest.fixture()
def env(tmp_path: Path):
    database = AuthDatabase(tmp_path / "auth" / "accounts.db")
    database.initialize()
    users = UserRepository(database)
    root = users.create_root(username="ai360", password_hash=hash_password("root-password"))
    user = users.create(
        username="plain-user",
        password_hash=hash_password("user-password"),
        role=AccountRole.USER,
        created_by=root.id,
    )
    resources = ResourceRepository(database)
    for voice_id, provider in (
        ("barbet-hung-yi-lee", "voxcpm"),
        ("voxcpm2-cosy-young-female-01", "voxcpm"),
        ("child-female-01", "cosyvoice"),
        ("same-id", "indextts"),
    ):
        resources.upsert_system_resource(
            resource_type=ResourceType.CUSTOM_VOICE,
            resource_id=voice_id,
            metadata={"provider": provider, "label": voice_id},
        )
        with database.transaction(write=True) as connection:
            connection.execute(
                "INSERT INTO resource_grants VALUES (?, 'custom_voice', ?, ?, ?)",
                (user.id, voice_id, root.id, _NOW),
            )
    return SimpleNamespace(
        database=database, runtime=SimpleNamespace(resources=resources), user=user,
    )


def _registered(env) -> set[str]:
    return {
        record.resource_id
        for record in env.runtime.resources.list_by_type(ResourceType.CUSTOM_VOICE)
    }


def _granted(env) -> set[str]:
    with env.database.transaction() as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT resource_id FROM resource_grants WHERE grantee_user_id = ?",
                (env.user.id,),
            )
        }


def test_excluded_voice_is_removed_with_its_grants(env):
    cfg = SimpleNamespace(
        tts_voxcpm_excluded_voices="barbet-hung-yi-lee",
        tts_cosyvoice_excluded_voices="",
    )

    system_resources.drop_excluded_voices(env.runtime, cfg)

    assert "barbet-hung-yi-lee" not in _registered(env)
    assert "barbet-hung-yi-lee" not in _granted(env)
    assert {"voxcpm2-cosy-young-female-01", "child-female-01", "same-id"} <= _registered(env)


def test_exclusion_only_applies_to_its_own_provider(env):
    """排除清單是 VoxCPM 的設定，不能順手刪掉別家同名的聲音。"""
    cfg = SimpleNamespace(
        tts_voxcpm_excluded_voices="same-id",
        tts_cosyvoice_excluded_voices=" child-female-01 , ",
    )

    system_resources.drop_excluded_voices(env.runtime, cfg)

    assert "same-id" in _registered(env)
    assert "child-female-01" not in _registered(env)
    assert "barbet-hung-yi-lee" in _registered(env)


def test_nothing_excluded_keeps_every_voice(env):
    before = _registered(env)
    cfg = SimpleNamespace(tts_voxcpm_excluded_voices="", tts_cosyvoice_excluded_voices="")

    system_resources.drop_excluded_voices(env.runtime, cfg)

    assert _registered(env) == before

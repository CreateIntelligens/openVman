"""ROOT-assigned administrator ceilings and their transitive narrowing."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.auth.database import AuthDatabase
from app.auth.models import (
    AccountRole,
    ResourceType,
)
from app.auth.policy import AccountPolicyError
from app.auth.repositories import (
    AccountAccessRepository,
    AdminScopeRepository,
    InvalidResourceGrantError,
    ResourceRepository,
    UserRepository,
)
from app.auth.resources import (
    ResourceNotFoundError,
    list_accessible_resources,
    resolve_resource,
)


@pytest.fixture()
def env(tmp_path: Path):
    database = AuthDatabase(tmp_path / "auth" / "accounts.db")
    database.initialize()
    users = UserRepository(database)
    resources = ResourceRepository(database)
    scopes = AdminScopeRepository(database)
    access = AccountAccessRepository(database)

    root = users.create_root(username="ai360", password_hash="hash")
    admin = users.create(
        username="admin-user",
        password_hash="hash",
        role=AccountRole.ADMIN,
        created_by=root.id,
    )

    # 兩個 TTS 聲線在範圍內，第三個刻意留在外面。
    for voice_id in ("voice-a", "voice-b", "voice-c"):
        resources.upsert_system_resource(
            resource_type=ResourceType.CUSTOM_VOICE,
            resource_id=voice_id,
            metadata={"label": voice_id},
        )
    for resource_type, resource_id in (
        (ResourceType.PROJECT, "project-a"),
        (ResourceType.PROJECT, "project-b"),
        (ResourceType.AVATAR_CHARACTER, "char-a"),
        (ResourceType.AVATAR_CHARACTER, "char-b"),
    ):
        resources.upsert_system_resource(
            resource_type=resource_type,
            resource_id=resource_id,
            metadata={"label": resource_id},
        )

    return {
        "database": database,
        "users": users,
        "resources": resources,
        "scopes": scopes,
        "access": access,
        "root": root,
        "admin": admin,
    }


def _scope_two_voices(env) -> None:
    env["scopes"].replace(
        admin_user_id=env["admin"].id,
        updated_by=env["root"].id,
        scoped=True,
        resources=[
            (ResourceType.CUSTOM_VOICE, "voice-a"),
            (ResourceType.CUSTOM_VOICE, "voice-b"),
            (ResourceType.PROJECT, "project-a"),
            (ResourceType.AVATAR_CHARACTER, "char-a"),
        ],
    )


def test_admin_without_a_scope_keeps_unrestricted_access(env):
    """遷移語義：ROOT 沒設限的既有 admin 行為完全不變。"""
    scope = env["scopes"].get(env["admin"].id)
    assert scope.scoped is False

    visible = list_accessible_resources(
        env["resources"],
        env["admin"],
        ResourceType.CUSTOM_VOICE,
        admin_scopes=env["scopes"],
    )
    assert {record.resource_id for record in visible} == {
        "voice-a",
        "voice-b",
        "voice-c",
    }


def test_scoped_admin_only_sees_resources_inside_its_ceiling(env):
    _scope_two_voices(env)

    visible = list_accessible_resources(
        env["resources"],
        env["admin"],
        ResourceType.CUSTOM_VOICE,
        admin_scopes=env["scopes"],
    )
    assert {record.resource_id for record in visible} == {"voice-a", "voice-b"}


def test_resource_outside_the_ceiling_resolves_as_not_found(env):
    """越界資源要與「不存在」無法區分，不洩漏它的存在。"""
    _scope_two_voices(env)

    resolved = resolve_resource(
        env["resources"],
        env["admin"],
        ResourceType.CUSTOM_VOICE,
        "voice-a",
        admin_scopes=env["scopes"],
    )
    assert resolved.resource_id == "voice-a"

    with pytest.raises(ResourceNotFoundError):
        resolve_resource(
            env["resources"],
            env["admin"],
            ResourceType.CUSTOM_VOICE,
            "voice-c",
            admin_scopes=env["scopes"],
        )


def test_root_is_never_scoped(env):
    """即使資料庫裡真的有 ROOT 的 scope 列，也不該生效。"""
    env["scopes"].replace(
        admin_user_id=env["admin"].id,
        updated_by=env["root"].id,
        scoped=True,
        resources=[(ResourceType.CUSTOM_VOICE, "voice-a")],
    )
    visible = list_accessible_resources(
        env["resources"],
        env["root"],
        ResourceType.CUSTOM_VOICE,
        admin_scopes=env["scopes"],
    )
    assert len(visible) == 3


def test_scoped_admin_cannot_grant_outside_its_ceiling(env):
    """收斂的核心：admin 開帳號時給不出自己沒有的資源。"""
    _scope_two_voices(env)

    with pytest.raises(InvalidResourceGrantError) as exc_info:
        env["users"].create(
            username="downstream",
            password_hash="hash",
            role=AccountRole.USER,
            created_by=env["admin"].id,
            grants=[
                (ResourceType.PROJECT, "project-a"),
                (ResourceType.AVATAR_CHARACTER, "char-a"),
                (ResourceType.CUSTOM_VOICE, "voice-c"),
            ],
            defaults=("project-a", "char-a", "cosyvoice", "voice-c"),
        )
    assert "voice-c" in str(exc_info.value)


def test_scoped_admin_can_grant_inside_its_ceiling(env):
    _scope_two_voices(env)

    created = env["users"].create(
        username="downstream-ok",
        password_hash="hash",
        role=AccountRole.USER,
        created_by=env["admin"].id,
        grants=[
            (ResourceType.PROJECT, "project-a"),
            (ResourceType.AVATAR_CHARACTER, "char-a"),
            (ResourceType.CUSTOM_VOICE, "voice-a"),
        ],
        defaults=("project-a", "char-a", "cosyvoice", "voice-a"),
    )

    granted = {
        (record.resource_type, record.resource_id)
        for record in env["access"].list_grants(created.id)
    }
    assert (ResourceType.CUSTOM_VOICE, "voice-a") in granted


def test_unscoped_admin_may_still_grant_anything(env):
    """沒設限的 admin 維持原本能力，遷移不影響現有流程。"""
    created = env["users"].create(
        username="downstream-free",
        password_hash="hash",
        role=AccountRole.USER,
        created_by=env["admin"].id,
        grants=[
            (ResourceType.PROJECT, "project-b"),
            (ResourceType.AVATAR_CHARACTER, "char-b"),
            (ResourceType.CUSTOM_VOICE, "voice-c"),
        ],
        defaults=("project-b", "char-b", "cosyvoice", "voice-c"),
    )
    assert created.id


def test_narrowing_a_scope_revokes_grants_that_fall_outside(env):
    """縮小範圍要撤掉既有的越界授權，否則收斂只擋得住新授權。"""
    downstream = env["users"].create(
        username="downstream-existing",
        password_hash="hash",
        role=AccountRole.USER,
        created_by=env["admin"].id,
        grants=[
            (ResourceType.PROJECT, "project-a"),
            (ResourceType.AVATAR_CHARACTER, "char-a"),
            (ResourceType.CUSTOM_VOICE, "voice-a"),
            (ResourceType.CUSTOM_VOICE, "voice-c"),
        ],
        defaults=("project-a", "char-a", "cosyvoice", "voice-a"),
    )
    before = {
        record.resource_id
        for record in env["access"].list_grants(downstream.id)
        if record.resource_type is ResourceType.CUSTOM_VOICE
    }
    assert before == {"voice-a", "voice-c"}

    _scope_two_voices(env)

    after = {
        record.resource_id
        for record in env["access"].list_grants(downstream.id)
        if record.resource_type is ResourceType.CUSTOM_VOICE
    }
    assert after == {"voice-a"}


def test_clearing_a_scope_restores_unrestricted_access(env):
    _scope_two_voices(env)
    assert env["scopes"].get(env["admin"].id).scoped is True

    env["scopes"].replace(
        admin_user_id=env["admin"].id,
        updated_by=env["root"].id,
        scoped=False,
        resources=[],
    )

    scope = env["scopes"].get(env["admin"].id)
    assert scope.scoped is False
    visible = list_accessible_resources(
        env["resources"],
        env["admin"],
        ResourceType.CUSTOM_VOICE,
        admin_scopes=env["scopes"],
    )
    assert len(visible) == 3


def test_an_empty_scope_is_distinct_from_no_scope(env):
    """ROOT 可以把某個 admin 的範圍設成空，這與「沒設限」必須不同。"""
    env["scopes"].replace(
        admin_user_id=env["admin"].id,
        updated_by=env["root"].id,
        scoped=True,
        resources=[],
    )

    scope = env["scopes"].get(env["admin"].id)
    assert scope.scoped is True
    visible = list_accessible_resources(
        env["resources"],
        env["admin"],
        ResourceType.CUSTOM_VOICE,
        admin_scopes=env["scopes"],
    )
    assert visible == []


def test_only_root_can_set_a_scope(env):
    other_admin = env["users"].create(
        username="admin-two",
        password_hash="hash",
        role=AccountRole.ADMIN,
        created_by=env["root"].id,
    )

    with pytest.raises(AccountPolicyError):
        env["scopes"].replace(
            admin_user_id=other_admin.id,
            updated_by=env["admin"].id,
            scoped=True,
            resources=[(ResourceType.CUSTOM_VOICE, "voice-a")],
        )


def test_scopes_apply_to_administrators_only(env):
    plain_user = env["users"].create(
        username="plain",
        password_hash="hash",
        role=AccountRole.USER,
        created_by=env["root"].id,
        grants=[
            (ResourceType.PROJECT, "project-a"),
            (ResourceType.AVATAR_CHARACTER, "char-a"),
            (ResourceType.CUSTOM_VOICE, "voice-a"),
        ],
        defaults=("project-a", "char-a", "cosyvoice", "voice-a"),
    )

    with pytest.raises(InvalidResourceGrantError):
        env["scopes"].replace(
            admin_user_id=plain_user.id,
            updated_by=env["root"].id,
            scoped=True,
            resources=[(ResourceType.CUSTOM_VOICE, "voice-a")],
        )


def test_scope_rejects_unregistered_resources(env):
    with pytest.raises(InvalidResourceGrantError):
        env["scopes"].replace(
            admin_user_id=env["admin"].id,
            updated_by=env["root"].id,
            scoped=True,
            resources=[(ResourceType.CUSTOM_VOICE, "voice-missing")],
        )


def test_narrowing_a_scope_leaves_no_dangling_default(env):
    """撤掉授權後，帳號的預設值不能還指著已撤銷的資源。

    預設值是登入時實際會套用的東西；指向一個已無授權的聲線，等於繞過收斂。
    """
    downstream = env["users"].create(
        username="downstream-default",
        password_hash="hash",
        role=AccountRole.USER,
        created_by=env["admin"].id,
        grants=[
            (ResourceType.PROJECT, "project-a"),
            (ResourceType.AVATAR_CHARACTER, "char-a"),
            (ResourceType.CUSTOM_VOICE, "voice-c"),
        ],
        # 預設聲線就是那個之後會被撤掉的 voice-c。
        defaults=("project-a", "char-a", "cosyvoice", "voice-c"),
    )
    assert env["access"].get_defaults(downstream.id).voice_id == "voice-c"

    _scope_two_voices(env)

    grants = {
        record.resource_id
        for record in env["access"].list_grants(downstream.id)
        if record.resource_type is ResourceType.CUSTOM_VOICE
    }
    assert "voice-c" not in grants

    defaults = env["access"].get_defaults(downstream.id)
    assert defaults is not None
    assert defaults.voice_id != "voice-c", (
        "預設聲線仍指向已撤銷的授權，帳號會繼續使用它"
    )


def test_root_can_give_an_administrator_its_own_resources(env):
    """管理員也能有自己的可用資源，由 ROOT 指定。"""
    grants, defaults = (
        env["access"].replace(
            user_id=env["admin"].id,
            granted_by=env["root"].id,
            grants=[
                (ResourceType.PROJECT, "project-a"),
                (ResourceType.AVATAR_CHARACTER, "char-a"),
                (ResourceType.CUSTOM_VOICE, "voice-a"),
            ],
            defaults=("project-a", "char-a", "cosyvoice", "voice-a"),
        )
    )
    assert defaults.voice_id == "voice-a"
    assert (ResourceType.CUSTOM_VOICE, "voice-a") in {
        (record.resource_type, record.resource_id) for record in grants
    }


def test_an_administrator_cannot_set_another_administrators_resources(env):
    """只有 ROOT 能設；否則 admin 之間可以互相改對方的資源。"""
    other = env["users"].create(
        username="admin-peer",
        password_hash="hash",
        role=AccountRole.ADMIN,
        created_by=env["root"].id,
    )

    with pytest.raises((InvalidResourceGrantError, AccountPolicyError)):
        env["access"].replace(
            user_id=other.id,
            granted_by=env["admin"].id,
            grants=[
                (ResourceType.PROJECT, "project-a"),
                (ResourceType.AVATAR_CHARACTER, "char-a"),
                (ResourceType.CUSTOM_VOICE, "voice-a"),
            ],
            defaults=("project-a", "char-a", "cosyvoice", "voice-a"),
        )


def test_an_administrator_manages_only_the_accounts_it_created(env):
    """admin 動不了別的 admin 建立的帳號。"""
    other_admin = env["users"].create(
        username="admin-other",
        password_hash="hash",
        role=AccountRole.ADMIN,
        created_by=env["root"].id,
    )
    foreign_user = env["users"].create(
        username="not-mine",
        password_hash="hash",
        role=AccountRole.USER,
        created_by=other_admin.id,
    )
    own_user = env["users"].create(
        username="mine",
        password_hash="hash",
        role=AccountRole.USER,
        created_by=env["admin"].id,
    )

    grants = [
        (ResourceType.PROJECT, "project-a"),
        (ResourceType.AVATAR_CHARACTER, "char-a"),
        (ResourceType.CUSTOM_VOICE, "voice-a"),
    ]
    defaults = ("project-a", "char-a", "cosyvoice", "voice-a")

    env["access"].replace(
        user_id=own_user.id,
        granted_by=env["admin"].id,
        grants=grants,
        defaults=defaults,
    )

    with pytest.raises(AccountPolicyError):
        env["access"].replace(
            user_id=foreign_user.id,
            granted_by=env["admin"].id,
            grants=grants,
            defaults=defaults,
        )


def test_root_manages_accounts_created_by_anyone(env):
    other_admin = env["users"].create(
        username="admin-third",
        password_hash="hash",
        role=AccountRole.ADMIN,
        created_by=env["root"].id,
    )
    their_user = env["users"].create(
        username="theirs",
        password_hash="hash",
        role=AccountRole.USER,
        created_by=other_admin.id,
    )

    _, defaults = env["access"].replace(
        user_id=their_user.id,
        granted_by=env["root"].id,
        grants=[
            (ResourceType.PROJECT, "project-a"),
            (ResourceType.AVATAR_CHARACTER, "char-a"),
            (ResourceType.CUSTOM_VOICE, "voice-a"),
        ],
        defaults=("project-a", "char-a", "cosyvoice", "voice-a"),
    )
    assert defaults.voice_id == "voice-a"

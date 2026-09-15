"""ROOT-assigned administrator ceilings and their transitive narrowing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

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
    resolve_admin_scope,
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


@pytest.mark.parametrize("operation", ["scope", "resource", "list"])
@pytest.mark.parametrize("failure", [RuntimeError, AttributeError])
def test_runtime_failure_aborts_admin_resource_access(env, operation, failure):
    _scope_two_voices(env)
    with patch(
        "app.auth.runtime.get_auth_runtime",
        side_effect=failure("auth runtime unavailable"),
    ), pytest.raises(failure, match="auth runtime unavailable"):
        if operation == "scope":
            resolve_admin_scope(env["admin"])
        elif operation == "resource":
            resolve_resource(
                env["resources"],
                env["admin"],
                ResourceType.CUSTOM_VOICE,
                "voice-c",
            )
        else:
            list_accessible_resources(
                env["resources"],
                env["admin"],
                ResourceType.CUSTOM_VOICE,
            )


def test_implicit_repository_enforces_admin_scope(env):
    _scope_two_voices(env)
    with patch(
        "app.auth.runtime.get_auth_runtime",
        return_value=Mock(admin_scopes=env["scopes"]),
    ):
        scope = resolve_admin_scope(env["admin"])

    assert scope.allows(ResourceType.CUSTOM_VOICE, "voice-a")
    assert not scope.allows(ResourceType.CUSTOM_VOICE, "voice-c")


def test_explicit_scope_repository_does_not_require_runtime(env):
    _scope_two_voices(env)
    with patch(
        "app.auth.runtime.get_auth_runtime",
        side_effect=RuntimeError("auth runtime unavailable"),
    ) as get_runtime:
        scope = resolve_admin_scope(env["admin"], env["scopes"])

    get_runtime.assert_not_called()
    assert scope.scoped
    assert not scope.allows(ResourceType.CUSTOM_VOICE, "voice-c")


def test_scope_repository_failure_aborts_access(env):
    scopes = Mock(spec=AdminScopeRepository)
    scopes.get.side_effect = RuntimeError("scope database unavailable")

    with pytest.raises(RuntimeError, match="scope database unavailable"):
        resolve_admin_scope(env["admin"], scopes)


def test_root_does_not_require_scope_runtime(env):
    with patch(
        "app.auth.runtime.get_auth_runtime",
        side_effect=RuntimeError("auth runtime unavailable"),
    ) as get_runtime:
        scope = resolve_admin_scope(env["root"])

    get_runtime.assert_not_called()
    assert not scope.scoped


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


def test_repointed_voice_default_switches_provider_with_it(env):
    """改指預設聲線時 provider 必須一起換。

    線上發現：撤掉 cosyvoice 的聲線後預設改指 indextts 的 hayley，但
    voice_provider 留著 cosyvoice，組成一個不存在的聲線。
    """
    env["resources"].upsert_system_resource(
        resource_type=ResourceType.CUSTOM_VOICE,
        resource_id="voice-a",
        metadata={"label": "voice-a", "provider": "indextts"},
    )
    env["resources"].upsert_system_resource(
        resource_type=ResourceType.CUSTOM_VOICE,
        resource_id="voice-c",
        metadata={"label": "voice-c", "provider": "cosyvoice"},
    )
    downstream = env["users"].create(
        username="downstream-provider",
        password_hash="hash",
        role=AccountRole.USER,
        created_by=env["admin"].id,
        grants=[
            (ResourceType.PROJECT, "project-a"),
            (ResourceType.AVATAR_CHARACTER, "char-a"),
            (ResourceType.CUSTOM_VOICE, "voice-a"),
            (ResourceType.CUSTOM_VOICE, "voice-c"),
        ],
        defaults=("project-a", "char-a", "cosyvoice", "voice-c"),
    )

    _scope_two_voices(env)

    defaults = env["access"].get_defaults(downstream.id)
    assert defaults is not None
    assert defaults.voice_id == "voice-a"
    assert defaults.voice_provider == "indextts", (
        "voice_id 換到 indextts 的聲線，provider 卻還是 cosyvoice"
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


def _delegate_admin(env):
    """A second-level admin created by the scoped admin, not by ROOT."""
    return env["users"].create(
        username="delegated-admin",
        password_hash="hash",
        role=AccountRole.ADMIN,
        created_by=env["admin"].id,
    )


def test_scoped_admin_delegates_only_a_subset_of_its_own_ceiling(env):
    _scope_two_voices(env)
    delegate = _delegate_admin(env)

    scope = env["scopes"].replace(
        admin_user_id=delegate.id,
        updated_by=env["admin"].id,
        scoped=True,
        resources=[(ResourceType.CUSTOM_VOICE, "voice-a")],
    )

    assert scope.scoped
    assert scope.allows(ResourceType.CUSTOM_VOICE, "voice-a")
    assert not scope.allows(ResourceType.CUSTOM_VOICE, "voice-b")


def test_scoped_admin_cannot_delegate_outside_its_own_ceiling(env):
    _scope_two_voices(env)
    delegate = _delegate_admin(env)

    # voice-c 不在委派者的上限內，整段委派必須被拒絕。
    with pytest.raises(InvalidResourceGrantError, match="outside your own scope"):
        env["scopes"].replace(
            admin_user_id=delegate.id,
            updated_by=env["admin"].id,
            scoped=True,
            resources=[
                (ResourceType.CUSTOM_VOICE, "voice-a"),
                (ResourceType.CUSTOM_VOICE, "voice-c"),
            ],
        )

    # 委派被拒後維持建立時繼承來的範圍，voice-c 沒有混進去。
    unchanged = env["scopes"].get(delegate.id)
    assert unchanged.scoped
    assert not unchanged.allows(ResourceType.CUSTOM_VOICE, "voice-c")


def test_scoped_admin_cannot_hand_out_unrestricted_scope(env):
    """否則受限 admin 可開一個 unscoped 下屬，再經由他取回全部資源。"""
    _scope_two_voices(env)
    delegate = _delegate_admin(env)

    with pytest.raises(InvalidResourceGrantError, match="unrestricted"):
        env["scopes"].replace(
            admin_user_id=delegate.id,
            updated_by=env["admin"].id,
            scoped=False,
            resources=[],
        )


def test_admin_cannot_set_scope_of_an_admin_it_did_not_create(env):
    _scope_two_voices(env)
    stranger = env["users"].create(
        username="stranger-admin",
        password_hash="hash",
        role=AccountRole.ADMIN,
        created_by=env["root"].id,
    )

    with pytest.raises(AccountPolicyError):
        env["scopes"].replace(
            admin_user_id=stranger.id,
            updated_by=env["admin"].id,
            scoped=True,
            resources=[(ResourceType.CUSTOM_VOICE, "voice-a")],
        )


def test_unscoped_admin_may_delegate_any_registered_resource(env):
    """沒有上限的 admin（未設 scope）不受子集限制。"""
    delegate = _delegate_admin(env)

    scope = env["scopes"].replace(
        admin_user_id=delegate.id,
        updated_by=env["admin"].id,
        scoped=True,
        resources=[(ResourceType.CUSTOM_VOICE, "voice-c")],
    )

    assert scope.allows(ResourceType.CUSTOM_VOICE, "voice-c")


def test_managed_subtree_spans_delegated_generations(env):
    """strong 看得到 tim，也看得到 tim 之後開出來的帳號。"""
    from app.auth.models import AccountType

    delegate = _delegate_admin(env)
    grandchild = env["users"].create(
        username="grandchild-user",
        password_hash="hash",
        role=AccountRole.USER,
        created_by=delegate.id,
    )
    unrelated = env["users"].create(
        username="unrelated-user",
        password_hash="hash",
        role=AccountRole.USER,
        created_by=env["root"].id,
    )

    visible = {
        user.username
        for user in env["users"].list_visible_subtree(
            env["admin"].id,
            account_type=AccountType.FORMAL,
        )
    }

    assert {"admin-user", "delegated-admin", "grandchild-user"} <= visible
    assert unrelated.username not in visible
    assert "ai360" not in visible
    assert grandchild.username in visible


def test_new_subordinate_admin_inherits_the_creator_ceiling(env):
    """受限 admin 開出來的 admin 不得預設不設限。"""
    _scope_two_voices(env)
    delegate = _delegate_admin(env)

    scope = env["scopes"].get(delegate.id)

    assert scope.scoped
    assert scope.allows(ResourceType.CUSTOM_VOICE, "voice-a")
    assert not scope.allows(ResourceType.CUSTOM_VOICE, "voice-c")


def test_root_created_admin_stays_unscoped_by_default(env):
    """ROOT 不設限，既有部署的「沒設過就不設限」行為必須保留。"""
    fresh = env["users"].create(
        username="root-made-admin",
        password_hash="hash",
        role=AccountRole.ADMIN,
        created_by=env["root"].id,
    )

    assert not env["scopes"].get(fresh.id).scoped


def test_shrinking_a_ceiling_cascades_down_the_delegation_chain(env):
    """上層被縮權後，下屬與孫節點都不得保留已超出的範圍。"""
    _scope_two_voices(env)
    delegate = _delegate_admin(env)
    grandchild = env["users"].create(
        username="grandchild-admin",
        password_hash="hash",
        role=AccountRole.ADMIN,
        created_by=delegate.id,
    )

    for target in (delegate.id, grandchild.id):
        env["scopes"].replace(
            admin_user_id=target,
            updated_by=env["admin"].id if target == delegate.id else delegate.id,
            scoped=True,
            resources=[
                (ResourceType.CUSTOM_VOICE, "voice-a"),
                (ResourceType.CUSTOM_VOICE, "voice-b"),
            ],
        )

    # ROOT 把上層收到只剩 voice-a。
    env["scopes"].replace(
        admin_user_id=env["admin"].id,
        updated_by=env["root"].id,
        scoped=True,
        resources=[(ResourceType.CUSTOM_VOICE, "voice-a")],
    )

    for target in (delegate.id, grandchild.id):
        scope = env["scopes"].get(target)
        assert scope.scoped
        assert scope.allows(ResourceType.CUSTOM_VOICE, "voice-a")
        assert not scope.allows(ResourceType.CUSTOM_VOICE, "voice-b")


def test_clearing_a_ceiling_empties_the_whole_chain(env):
    """清空上層等於整條鏈失去資源，不是讓下屬變成不設限。"""
    _scope_two_voices(env)
    delegate = _delegate_admin(env)
    env["scopes"].replace(
        admin_user_id=delegate.id,
        updated_by=env["admin"].id,
        scoped=True,
        resources=[(ResourceType.CUSTOM_VOICE, "voice-a")],
    )

    env["scopes"].replace(
        admin_user_id=env["admin"].id,
        updated_by=env["root"].id,
        scoped=True,
        resources=[],
    )

    scope = env["scopes"].get(delegate.id)
    assert scope.scoped
    assert not scope.allows(ResourceType.CUSTOM_VOICE, "voice-a")

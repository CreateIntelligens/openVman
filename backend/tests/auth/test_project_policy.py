"""Project voice policies: storage, validation and the admin API."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import project_routes
from app.auth.middleware import FailClosedAuthMiddleware
from app.auth.models import AccountRole, ResourceType
from app.auth.repository_errors import InvalidProjectPolicyError
from app.auth.runtime import get_auth_runtime

_GRANTS = [
    (ResourceType.PROJECT, "p1"),
    (ResourceType.AVATAR_CHARACTER, "a1"),
    (ResourceType.CUSTOM_VOICE, "voice-a"),
]
_DEFAULTS = ("p1", "a1", "indextts", "voice-a")


@pytest.fixture
def env():
    runtime = get_auth_runtime()
    root = runtime.users.create_root(username="ai360", password_hash="unused")
    for resource_type, resource_id, metadata in [
        (ResourceType.PROJECT, "p1", {}),
        (ResourceType.PROJECT, "p2", {}),
        (ResourceType.AVATAR_CHARACTER, "a1", {}),
        (ResourceType.CUSTOM_VOICE, "voice-a", {"provider": "indextts"}),
        (ResourceType.CUSTOM_VOICE, "voice-b", {"provider": "cosyvoice"}),
        (ResourceType.CUSTOM_VOICE, "edge-a", {"provider": "edge-tts"}),
        *(
            (ResourceType.ASR_ENGINE, engine, {})
            for engine in ("breeze", "openai", "r2t2", "gemini-live")
        ),
    ]:
        runtime.resources.upsert_system_resource(
            resource_type=resource_type, resource_id=resource_id,
            metadata=metadata,
        )
    user = runtime.users.create(
        username="member", password_hash="unused", role=AccountRole.USER,
        created_by=root.id, grants=_GRANTS, defaults=_DEFAULTS,
    )
    editor = runtime.users.create(
        username="editor", password_hash="unused", role=AccountRole.USER,
        created_by=root.id, grants=_GRANTS, defaults=_DEFAULTS,
        admin_portal_access=True,
    )
    admin = runtime.users.create(
        username="scoped-admin", password_hash="unused", role=AccountRole.ADMIN,
        created_by=root.id,
    )
    runtime.admin_scopes.replace(
        admin_user_id=admin.id, updated_by=root.id, scoped=True,
        resources=[
            (ResourceType.PROJECT, "p1"),
            (ResourceType.ASR_ENGINE, "breeze"),
            (ResourceType.CUSTOM_VOICE, "voice-a"),
        ],
    )
    app = FastAPI()
    app.include_router(project_routes.router)
    app.add_middleware(FailClosedAuthMiddleware, runtime=runtime)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(
            runtime=runtime, root=root, user=user, editor=editor,
            admin=admin, client=client,
        )


def _headers(env, account):
    return {"Authorization": f"Bearer {env.runtime.tokens.issue(account)}"}


def _put(env, account, project_id="p1", **body):
    return env.client.put(
        f"/api/v1/projects/{project_id}/policy",
        headers=_headers(env, account), json=body,
    )


def test_missing_policy_reads_as_unrestricted(env):
    policy = env.runtime.project_policies.get("p1")
    assert policy.allowed_asr_engines == ()
    assert policy.allowed_tts_voices == ()
    assert policy.default_asr_engine is None
    assert not policy.restricts_asr and not policy.restricts_tts
    assert policy.allows_asr("anything") and policy.allows_voice("anything")


def test_replace_round_trips_and_normalizes(env):
    record = env.runtime.project_policies.replace(
        project_id="p1",
        allowed_asr_engines=[" breeze ", "openai", "breeze", ""],
        default_asr_engine="openai",
        taiwanese_asr_engine="breeze",
        allowed_tts_voices=["voice-a", "edge-a"],
        default_tts_voice=" ",
        updated_by=env.root.id,
    )
    assert record.allowed_asr_engines == ("breeze", "openai")
    assert record.default_tts_voice is None
    stored = env.runtime.project_policies.get("p1")
    assert stored.allowed_asr_engines == ("breeze", "openai")
    assert stored.default_asr_engine == "openai"
    assert stored.taiwanese_asr_engine == "breeze"
    assert stored.allowed_tts_voices == ("voice-a", "edge-a")
    assert stored.updated_by == env.root.id
    assert stored.narrow_asr({"breeze", "sensevoice"}) == {"breeze"}


@pytest.mark.parametrize(("fields", "message"), [
    ({"allowed_asr_engines": ["nope"]}, "not registered"),
    ({"default_asr_engine": "nope"}, "not registered"),
    ({"allowed_tts_voices": ["ghost"]}, "not registered"),
    ({"default_tts_voice": "ghost"}, "not registered"),
    (
        {"allowed_asr_engines": ["breeze"], "default_asr_engine": "openai"},
        "default_asr_engine",
    ),
    (
        {"allowed_asr_engines": ["openai"], "taiwanese_asr_engine": "breeze"},
        "taiwanese_asr_engine",
    ),
    ({"taiwanese_asr_engine": "gemini-live"}, "batch"),
    (
        {"allowed_tts_voices": ["voice-a"], "default_tts_voice": "voice-b"},
        "default_tts_voice",
    ),
])
def test_replace_rejects_invalid_policies(env, fields, message):
    with pytest.raises(InvalidProjectPolicyError, match=message):
        env.runtime.project_policies.replace(
            project_id="p1", updated_by=env.root.id, **fields,
        )
    assert env.runtime.project_policies.get("p1").updated_at is None


def test_default_without_allowlist_only_needs_to_exist(env):
    record = env.runtime.project_policies.replace(
        project_id="p1", default_asr_engine="openai",
        default_tts_voice="voice-b", updated_by=env.root.id,
    )
    assert not record.restricts_asr and not record.restricts_tts
    assert record.default_asr_engine == "openai"


def test_unregistered_project_is_rejected(env):
    with pytest.raises(InvalidProjectPolicyError, match="project"):
        env.runtime.project_policies.replace(
            project_id="missing", allowed_asr_engines=["breeze"],
            updated_by=env.root.id,
        )


def test_clearing_everything_removes_the_row_and_project_delete_cascades(env):
    policies = env.runtime.project_policies
    policies.replace(
        project_id="p1", allowed_asr_engines=["breeze"], updated_by=env.root.id,
    )
    policies.replace(project_id="p1", updated_by=env.root.id)
    assert policies.get("p1").updated_at is None

    policies.replace(
        project_id="p2", allowed_tts_voices=["voice-a"], updated_by=env.root.id,
    )
    env.runtime.resources.unregister(ResourceType.PROJECT, "p2")
    with env.runtime.database.transaction() as connection:
        rows = connection.execute(
            "SELECT COUNT(*) FROM project_policies WHERE project_id = 'p2'"
        ).fetchone()[0]
    assert rows == 0


def test_migration_is_rerunnable(env):
    env.runtime.project_policies.replace(
        project_id="p1", allowed_asr_engines=["breeze"], updated_by=env.root.id,
    )
    env.runtime.database.initialize()
    assert env.runtime.project_policies.get("p1").allowed_asr_engines == ("breeze",)


def test_root_puts_and_editor_reads_policy(env):
    response = _put(
        env, env.root,
        allowed_asr_engines=["breeze", "openai"], default_asr_engine="breeze",
        taiwanese_asr_engine="breeze", allowed_tts_voices=["voice-a"],
        default_tts_voice="voice-a",
    )
    assert response.status_code == 200, response.text
    assert response.json()["allowed_asr_engines"] == ["breeze", "openai"]
    assert response.json()["updated_by"] == env.root.id

    read = env.client.get(
        "/api/v1/projects/p1/policy", headers=_headers(env, env.editor),
    )
    assert read.status_code == 200
    assert read.json()["default_tts_voice"] == "voice-a"


def test_unset_policy_is_returned_as_unrestricted(env):
    read = env.client.get(
        "/api/v1/projects/p1/policy", headers=_headers(env, env.root),
    )
    assert read.status_code == 200
    assert read.json() == {
        "project_id": "p1",
        "allowed_asr_engines": [], "default_asr_engine": None,
        "taiwanese_asr_engine": None, "allowed_tts_voices": [],
        "default_tts_voice": None, "updated_by": None, "updated_at": None,
        "allowed_characters": [], "default_character_id": None,
        "allowed_backgrounds": [], "default_background_id": None,
        "allowed_mascots": [], "default_mascot_id": None,
        "tts_engine_order": [], "asr_engine_order": [],
    }


def test_plain_user_cannot_read_or_write(env):
    read = env.client.get(
        "/api/v1/projects/p1/policy", headers=_headers(env, env.user),
    )
    assert read.status_code == 404
    assert _put(env, env.user, allowed_asr_engines=["breeze"]).status_code == 403
    assert _put(env, env.editor, allowed_asr_engines=["breeze"]).status_code == 403


def test_validation_errors_are_422(env):
    response = _put(
        env, env.root,
        allowed_tts_voices=["voice-a"], default_tts_voice="voice-b",
    )
    assert response.status_code == 422
    assert "default_tts_voice" in response.json()["detail"]
    assert _put(env, env.root, unknown_field=1).status_code == 422


def test_scoped_admin_stays_inside_its_ceiling(env):
    assert _put(
        env, env.admin, allowed_asr_engines=["breeze"],
        allowed_tts_voices=["voice-a"],
    ).status_code == 200
    outside = _put(env, env.admin, allowed_asr_engines=["breeze", "openai"])
    assert outside.status_code == 403
    assert "asr_engine/openai" in outside.json()["detail"]
    # 範圍外的專案對受限 admin 來說等同不存在。
    assert _put(env, env.admin, project_id="p2").status_code == 404


def test_engine_order_round_trips(env):
    record = env.runtime.project_policies.replace(
        project_id="p1",
        tts_engine_order=["voxcpm", " cosyvoice ", "voxcpm", "edge-tts"],
        asr_engine_order=["sensevoice", "breeze"],
        updated_by=env.root.id,
    )
    assert record.tts_engine_order == ("voxcpm", "cosyvoice", "edge-tts")
    assert record.asr_engine_order == ("sensevoice", "breeze")
    stored = env.runtime.project_policies.get("p1")
    assert stored.tts_engine_order == ("voxcpm", "cosyvoice", "edge-tts")
    assert stored.asr_engine_order == ("sensevoice", "breeze")
    # 只有順位也算有設定：清掉後整列消失。
    env.runtime.project_policies.replace(project_id="p1", updated_by=env.root.id)
    assert env.runtime.project_policies.get("p1").tts_engine_order == ()


@pytest.mark.parametrize(("fields", "message"), [
    ({"tts_engine_order": ["indextts", "polly"]}, "unknown engines"),
    ({"asr_engine_order": ["gemini-live"]}, "batch ASR"),
    (
        {"allowed_asr_engines": ["breeze"], "asr_engine_order": ["sensevoice"]},
        "subset of allowed_asr_engines",
    ),
])
def test_engine_order_is_validated(env, fields, message):
    with pytest.raises(InvalidProjectPolicyError, match=message):
        env.runtime.project_policies.replace(
            project_id="p1", updated_by=env.root.id, **fields,
        )


def test_engine_order_columns_are_added_to_an_existing_database(env):
    """正式機已套用 23 的資料庫也要拿到順位欄位（schema 25 獨立一版）。"""
    from app.auth.schema_migrations import _PROJECT_ENGINE_ORDER_SCHEMA_VERSION

    database = env.runtime.project_policies.database
    with database.transaction(write=True) as connection:
        connection.execute(
            "DELETE FROM schema_migrations WHERE version = ?",
            (_PROJECT_ENGINE_ORDER_SCHEMA_VERSION,),
        )
    database.initialize()
    with database.transaction() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(project_policies)")}
        versions = {row["version"] for row in connection.execute("SELECT version FROM schema_migrations")}
    assert {"tts_engine_order_json", "asr_engine_order_json"} <= columns
    assert _PROJECT_ENGINE_ORDER_SCHEMA_VERSION in versions
    # 再跑一次不會炸。
    database.initialize()

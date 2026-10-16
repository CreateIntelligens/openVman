"""Project-scoped resources: assignments, effective resolution, and APIs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import project_routes
from app.auth.middleware import FailClosedAuthMiddleware
from app.auth.models import (
    AccountRole,
    ResourceType,
    ResourceVisibility,
)
from app.auth.project_resources import (
    effective_project_default,
    effective_project_resources,
)
from app.auth.repository_errors import InvalidProjectPolicyError
from app.auth.runtime import get_auth_runtime


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AVATAR_ASSETS_DIR", str(tmp_path / "avatar"))
    monkeypatch.setenv("AVATAR_BACKGROUNDS_DIR", str(tmp_path / "backgrounds"))
    monkeypatch.setenv("AVATAR_MASCOTS_DIR", str(tmp_path / "mascots"))
    from app.config import get_tts_config
    get_tts_config.cache_clear()
    from app.routes import avatar as avatar_routes, backgrounds as background_routes, mascots as mascot_routes
    avatar_routes.reset_store()
    background_routes.reset_store()
    mascot_routes.reset_store()

    runtime = get_auth_runtime()
    root = runtime.users.create_root(username="ai360", password_hash="unused")

    # 註冊測試專案
    runtime.resources.upsert_system_resource(
        resource_type=ResourceType.PROJECT,
        resource_id="proj-1",
        metadata={"name": "Project One"},
    )
    runtime.resources.upsert_system_resource(
        resource_type=ResourceType.PROJECT,
        resource_id="proj-2",
        metadata={"name": "Project Two"},
    )

    # 全域資源
    runtime.resources.upsert_system_resource(
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="char-global-1",
        metadata={"label": "Global Char 1"},
    )
    runtime.resources.upsert_system_resource(
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="char-global-2",
        metadata={"label": "Global Char 2"},
    )
    runtime.resources.upsert_system_resource(
        resource_type=ResourceType.AVATAR_BACKGROUND,
        resource_id="bg-global-1",
        metadata={"label": "Global Bg 1"},
    )
    runtime.resources.upsert_system_resource(
        resource_type=ResourceType.AVATAR_MASCOT,
        resource_id="mascot-global-1",
        metadata={"label": "Global Mascot 1"},
    )
    runtime.resources.upsert_system_resource(
        resource_type=ResourceType.CUSTOM_VOICE,
        resource_id="voice-global-1",
        metadata={"label": "Global Voice 1", "provider": "indextts"},
    )
    runtime.resources.upsert_system_resource(
        resource_type=ResourceType.ASR_ENGINE,
        resource_id="breeze",
        metadata={"label": "Breeze ASR"},
    )

    # 專案專屬資源 (visibility=project, owner_project_id=proj-1)
    runtime.resources.register(
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="char-proj-1",
        owner_user_id=None,
        visibility=ResourceVisibility.PROJECT,
        owner_project_id="proj-1",
        metadata={"label": "Project Char 1"},
    )
    runtime.resources.register(
        resource_type=ResourceType.AVATAR_BACKGROUND,
        resource_id="bg-proj-1",
        owner_user_id=None,
        visibility=ResourceVisibility.PROJECT,
        owner_project_id="proj-1",
        metadata={"label": "Project Bg 1"},
    )

    # 一般成員與管理員
    member = runtime.users.create(
        username="member",
        password_hash="unused",
        role=AccountRole.USER,
        created_by=root.id,
        grants=[
            (ResourceType.PROJECT, "proj-1"),
            (ResourceType.AVATAR_CHARACTER, "char-global-1"),
            (ResourceType.AVATAR_BACKGROUND, "bg-global-1"),
            (ResourceType.AVATAR_MASCOT, "mascot-global-1"),
            (ResourceType.CUSTOM_VOICE, "voice-global-1"),
            (ResourceType.ASR_ENGINE, "breeze"),
        ],
        defaults=("proj-1", "char-global-1", "indextts", "voice-global-1"),
    )
    admin = runtime.users.create(
        username="admin-user",
        password_hash="unused",
        role=AccountRole.ADMIN,
        created_by=root.id,
    )
    # 受限管理員擁有 proj-1 與 char-global-1 管理權限
    runtime.admin_scopes.replace(
        admin_user_id=admin.id,
        updated_by=root.id,
        scoped=True,
        resources=[
            (ResourceType.PROJECT, "proj-1"),
            (ResourceType.AVATAR_CHARACTER, "char-global-1"),
        ],
    )

    non_member = runtime.users.create(
        username="non-member",
        password_hash="unused",
        role=AccountRole.USER,
        created_by=root.id,
    )

    from app.routes import avatar as avatar_routes, backgrounds as background_routes, mascots as mascot_routes, static_assets as static_assets_routes

    app = FastAPI()
    app.include_router(project_routes.router)
    app.include_router(avatar_routes.router)
    app.include_router(background_routes.router)
    app.include_router(mascot_routes.router)
    app.include_router(static_assets_routes.router)
    app.add_middleware(FailClosedAuthMiddleware, runtime=runtime)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    with TestClient(app, raise_server_exceptions=True) as client:
        yield SimpleNamespace(
            runtime=runtime,
            root=root,
            member=member,
            non_member=non_member,
            admin=admin,
            client=client,
            tmp_path=tmp_path,
        )


def _headers(env, account):
    return {"Authorization": f"Bearer {env.runtime.tokens.issue(account)}"}


def test_project_resource_assignment_repository_crud(env):
    repo = env.runtime.project_resource_assignments

    # 指派資源
    record = repo.assign(
        project_id="proj-1",
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="char-global-2",
        assigned_by=env.root.id,
    )
    assert record.project_id == "proj-1"
    assert record.resource_id == "char-global-2"
    assert record.assigned_by == env.root.id

    # 冪等性：再次指派相同項目
    record_again = repo.assign(
        project_id="proj-1",
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="char-global-2",
        assigned_by=env.root.id,
    )
    assert record_again.project_id == "proj-1"

    # 查詢與判斷
    assert repo.is_assigned("proj-1", ResourceType.AVATAR_CHARACTER, "char-global-2")
    assert not repo.is_assigned("proj-1", ResourceType.AVATAR_CHARACTER, "non-existent")

    assigned_list = repo.list_for_project("proj-1", ResourceType.AVATAR_CHARACTER)
    assert len(assigned_list) == 1
    assert assigned_list[0].resource_id == "char-global-2"

    # 解除指派
    assert repo.unassign(
        project_id="proj-1",
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="char-global-2",
    )
    assert not repo.is_assigned("proj-1", ResourceType.AVATAR_CHARACTER, "char-global-2")
    assert not repo.unassign(
        project_id="proj-1",
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="char-global-2",
    )


def test_assignment_api_root_only_and_audit(env):
    # 非 ROOT (admin) 呼叫指派 -> 403
    r = env.client.post(
        "/api/v1/projects/proj-1/assignments",
        headers=_headers(env, env.admin),
        json={
            "resource_type": "avatar_character",
            "resource_id": "char-global-2",
        },
    )
    assert r.status_code == 403

    # ROOT 呼叫指派 -> 200
    r = env.client.post(
        "/api/v1/projects/proj-1/assignments",
        headers=_headers(env, env.root),
        json={
            "resource_type": "avatar_character",
            "resource_id": "char-global-2",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["assignment"]["resource_id"] == "char-global-2"

    # 檢查稽核日誌
    with env.runtime.database.transaction() as conn:
        audit = conn.execute(
            "SELECT action, metadata_json FROM auth_audit_events WHERE action = 'project_resource_assigned' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert audit is not None
        assert audit["action"] == "project_resource_assigned"
        assert "proj-1" in audit["metadata_json"]

    # 非 ROOT 呼叫解除指派 -> 403
    r = env.client.delete(
        "/api/v1/projects/proj-1/assignments/avatar_character/char-global-2",
        headers=_headers(env, env.admin),
    )
    assert r.status_code == 403

    # ROOT 呼叫解除指派 -> 200
    r = env.client.delete(
        "/api/v1/projects/proj-1/assignments/avatar_character/char-global-2",
        headers=_headers(env, env.root),
    )
    assert r.status_code == 200

    with env.runtime.database.transaction() as conn:
        audit = conn.execute(
            "SELECT action, metadata_json FROM auth_audit_events WHERE action = 'project_resource_unassigned' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert audit is not None
        assert audit["action"] == "project_resource_unassigned"
        assert "proj-1" in audit["metadata_json"]


def test_get_project_resources_api(env):
    # 指派 char-global-2 給 proj-1
    env.runtime.project_resource_assignments.assign(
        project_id="proj-1",
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="char-global-2",
        assigned_by=env.root.id,
    )
    # 設定 policy 限制
    env.runtime.project_policies.replace(
        project_id="proj-1",
        allowed_characters=["char-global-1", "char-proj-1"],
        default_character_id="char-proj-1",
        default_background_id="bg-proj-1",
        updated_by=env.root.id,
    )

    r = env.client.get(
        "/api/v1/projects/proj-1/resources",
        headers=_headers(env, env.member),
    )
    assert r.status_code == 200
    payload = r.json()
    assert "avatar_character" in payload
    assert "avatar_background" in payload
    assert "avatar_mascot" in payload
    assert "custom_voice" in payload
    assert "asr_engine" in payload
    assert "characters" not in payload

    char_ids = {c["resource_id"]: c for c in payload["avatar_character"]}
    # char-proj-1 (project, is_default=True)
    assert "char-proj-1" in char_ids
    assert char_ids["char-proj-1"]["source"] == "project"
    assert char_ids["char-proj-1"]["is_default"] is True

    # char-global-2 (assigned)
    assert "char-global-2" in char_ids
    assert char_ids["char-global-2"]["source"] == "assigned"

    # char-global-1 (grant)
    assert "char-global-1" in char_ids
    assert char_ids["char-global-1"]["source"] == "grant"


def test_effective_project_resources_and_default_priority(env):
    # 指派 char-global-2 給 proj-1
    env.runtime.project_resource_assignments.assign(
        project_id="proj-1",
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="char-global-2",
        assigned_by=env.root.id,
    )

    entries = effective_project_resources(
        env.runtime,
        env.member,
        "proj-1",
        ResourceType.AVATAR_CHARACTER,
    )
    entry_map = {e.resource_id: e.source for e in entries}

    # 包含 grant(char-global-1), project(char-proj-1), assigned(char-global-2)
    assert entry_map["char-global-1"] == "grant"
    assert entry_map["char-proj-1"] == "project"
    assert entry_map["char-global-2"] == "assigned"

    # 優先級：如果同一個 id 同時出現在 assigned 與 system，assigned 優先
    env.runtime.project_resource_assignments.assign(
        project_id="proj-1",
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="char-global-1",
        assigned_by=env.root.id,
    )
    entries = effective_project_resources(
        env.runtime,
        env.member,
        "proj-1",
        ResourceType.AVATAR_CHARACTER,
    )
    entry_map = {e.resource_id: e.source for e in entries}
    assert entry_map["char-global-1"] == "assigned"

    # 預設值優先級測試：
    # 1. 專案 policy 有預設 -> 取專案預設
    env.runtime.project_policies.replace(
        project_id="proj-1",
        default_character_id="char-proj-1",
        updated_by=env.root.id,
    )
    def_char = effective_project_default(
        env.runtime,
        env.member,
        "proj-1",
        ResourceType.AVATAR_CHARACTER,
    )
    assert def_char == "char-proj-1"

    # 2. 專案 policy 無預設 -> 取帳號預設 (char-global-1)
    env.runtime.project_policies.replace(
        project_id="proj-1",
        default_character_id=None,
        updated_by=env.root.id,
    )
    def_char = effective_project_default(
        env.runtime,
        env.member,
        "proj-1",
        ResourceType.AVATAR_CHARACTER,
    )
    assert def_char == "char-global-1"


def test_orphan_resource_on_project_unregister(env):
    # 專案解除註冊時，專案專屬資源 owner_project_id 應被設為 NULL (成為 orphan)
    res_repo = env.runtime.resources

    # 原本是 proj-1 的專屬資源
    res = res_repo.get(ResourceType.AVATAR_CHARACTER, "char-proj-1")
    assert res.owner_project_id == "proj-1"
    assert res.visibility == ResourceVisibility.PROJECT

    # unregister 專案
    res_repo.unregister(ResourceType.PROJECT, "proj-1")

    # 專屬資源依然存在，但 owner_project_id 變成 None
    res_after = res_repo.get(ResourceType.AVATAR_CHARACTER, "char-proj-1")
    assert res_after is not None
    assert res_after.owner_project_id is None
    assert res_after.visibility == ResourceVisibility.PROJECT

    # 孤兒資源列表
    orphans = res_repo.list_orphans(resource_type=ResourceType.AVATAR_CHARACTER)
    assert any(o.resource_id == "char-proj-1" for o in orphans)


def test_scoped_admin_project_policy_with_project_and_assigned_resources(env):
    # 將 char-global-2 指派給 proj-1
    env.runtime.project_resource_assignments.assign(
        project_id="proj-1",
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="char-global-2",
        assigned_by=env.root.id,
    )

    # 受限 admin 的帳號 scope 只有 char-global-1，沒有 char-global-2 或 char-proj-1。
    # 但是 char-proj-1 是專案專屬資源，char-global-2 是 ROOT 指派資源，
    # 因此受限 admin 在修改 proj-1 的 policy 時，可以使用這兩者！
    r = env.client.put(
        "/api/v1/projects/proj-1/policy",
        headers=_headers(env, env.admin),
        json={
            "allowed_characters": ["char-global-1", "char-proj-1", "char-global-2"],
            "default_character_id": "char-proj-1",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert set(data["allowed_characters"]) == {
        "char-global-1",
        "char-proj-1",
        "char-global-2",
    }
    assert data["default_character_id"] == "char-proj-1"


def test_avatar_route_project_scope(env, monkeypatch):
    from app.routes import avatar as avatar_routes

    monkeypatch.setattr(
        avatar_routes.get_store(),
        "list_characters",
        lambda: [
            {"char_id": "char-global-1", "label": "Global Char 1"},
            {"char_id": "char-global-2", "label": "Global Char 2"},
            {"char_id": "char-proj-1", "label": "Project Char 1"},
        ],
    )

    # 帶 project_id: 成員可見 char-global-1 (system) 與 char-proj-1 (project)
    r = env.client.get(
        "/api/v1/avatar",
        params={"project_id": "proj-1"},
        headers=_headers(env, env.member),
    )
    assert r.status_code == 200
    chars = {c["char_id"]: c for c in r.json()["characters"]}
    assert "char-global-1" in chars
    assert chars["char-global-1"]["source"] == "grant"
    assert "char-proj-1" in chars
    assert chars["char-proj-1"]["source"] == "project"
    assert "char-global-2" not in chars

    # 不帶 project_id: 成員只可見全域授權資源 char-global-1，不能看見專案資源 char-proj-1
    r_unscoped = env.client.get(
        "/api/v1/avatar",
        headers=_headers(env, env.member),
    )
    assert r_unscoped.status_code == 200
    unscoped_chars = {c["char_id"]: c for c in r_unscoped.json()["characters"]}
    assert "char-global-1" in unscoped_chars
    assert "char-proj-1" not in unscoped_chars


def test_backgrounds_route_project_scope(env, monkeypatch):
    from app.routes import backgrounds as background_routes

    monkeypatch.setattr(
        background_routes.get_store(),
        "list_backgrounds",
        lambda: [
            {"background_id": "bg-global-1", "label": "Global Bg 1"},
            {"background_id": "bg-proj-1", "label": "Project Bg 1"},
        ],
    )

    # 帶 project_id: 成員可見 bg-global-1 與 bg-proj-1
    r = env.client.get(
        "/api/v1/backgrounds",
        params={"project_id": "proj-1"},
        headers=_headers(env, env.member),
    )
    assert r.status_code == 200
    bgs = {b["background_id"]: b for b in r.json()["backgrounds"]}
    assert "bg-global-1" in bgs
    assert bgs["bg-global-1"]["source"] == "grant"
    assert "bg-proj-1" in bgs
    assert bgs["bg-proj-1"]["source"] == "project"

    # 不帶 project_id: 成員不能看見 bg-proj-1
    r_unscoped = env.client.get(
        "/api/v1/backgrounds",
        headers=_headers(env, env.member),
    )
    assert r_unscoped.status_code == 200
    unscoped_bgs = {b["background_id"]: b for b in r_unscoped.json()["backgrounds"]}
    assert "bg-global-1" in unscoped_bgs
    assert "bg-proj-1" not in unscoped_bgs


def test_mascots_route_project_scope(env, monkeypatch):
    from app.routes import mascots as mascot_routes

    monkeypatch.setattr(
        mascot_routes.get_store(),
        "list_mascots",
        lambda: [
            {"mascot_id": "mascot-global-1", "label": "Global Mascot 1", "engine": "vrm"},
        ],
    )

    # 帶 project_id
    r = env.client.get(
        "/api/v1/avatar/mascots",
        params={"project_id": "proj-1"},
        headers=_headers(env, env.member),
    )
    assert r.status_code == 200
    mascots = {m["mascot_id"]: m for m in r.json()["mascots"]}
    assert "mascot-global-1" in mascots
    assert mascots["mascot-global-1"]["source"] == "grant"


def test_migration_23_idempotency_and_v22_upgrade(tmp_path):
    """Migration 23: v22 -> v23 升級、舊資料 owner_project_id 為 NULL，多次執行保證冪等。"""
    from app.auth.database import AuthDatabase
    from app.auth.models import ResourceType
    from app.auth.resource_repository import ResourceRepository

    db = AuthDatabase(str(tmp_path / "migration23_test.db"))
    db.initialize()
    resources = ResourceRepository(db)
    resources.upsert_system_resource(
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="legacy-char-1",
        metadata={"label": "Legacy"},
    )

    # 模擬 v22 資料庫：以無 owner_project_id 的結構重建 resources 表、移除 project_resource_assignments 表與 version 23 記錄
    with db.transaction(write=True) as connection:
        connection.execute("DROP TABLE IF EXISTS project_resource_assignments")
        connection.execute("DELETE FROM schema_migrations WHERE version = 23")
        connection.execute(
            """
            CREATE TABLE resources_v22 (
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                owner_user_id TEXT,
                visibility TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (resource_type, resource_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO resources_v22
            SELECT resource_type, resource_id, owner_user_id, visibility, created_at, metadata_json
            FROM resources
            """
        )
        connection.execute("DROP TABLE resources")
        connection.execute("ALTER TABLE resources_v22 RENAME TO resources")

    # 執行 v22 -> v23 升級
    db.initialize()

    with db.transaction() as c:
        row = dict(
            c.execute(
                "SELECT * FROM resources WHERE resource_id = 'legacy-char-1'"
            ).fetchone()
        )
        assert "owner_project_id" in row
        assert row["owner_project_id"] is None
        # 檢查 project_resource_assignments 表已建立
        assignments = c.execute(
            "SELECT count(*) as cnt FROM project_resource_assignments"
        ).fetchone()
        assert assignments["cnt"] == 0

    # 再次執行 initialize 驗證冪等性
    db.initialize()
    with db.transaction() as c:
        applied = [
            r["version"]
            for r in c.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        assert 23 in applied
        assert applied == sorted(set(applied))


def test_migration_23_foreign_keys_and_cascade(tmp_path):
    """外鍵約束與 CASCADE：刪除資源或刪除專案時，assignments 連帶清除。"""
    from app.auth.database import AuthDatabase
    from app.auth.models import ResourceType
    from app.auth.project_resource_assignment_repository import (
        ProjectResourceAssignmentRepository,
    )
    from app.auth.resource_repository import ResourceRepository
    from app.auth.user_repository import UserRepository

    db = AuthDatabase(str(tmp_path / "cascade.db"))
    db.initialize()
    resources = ResourceRepository(db)
    assignments = ProjectResourceAssignmentRepository(db)
    users = UserRepository(db)
    root = users.create_root(username="ai360", password_hash="hash")

    # 建立專案與資源
    resources.upsert_system_resource(resource_type=ResourceType.PROJECT, resource_id="p-casc", metadata={})
    resources.upsert_system_resource(resource_type=ResourceType.AVATAR_CHARACTER, resource_id="c-casc", metadata={})

    assignments.assign(project_id="p-casc", resource_type=ResourceType.AVATAR_CHARACTER, resource_id="c-casc", assigned_by=root.id)
    assert assignments.is_assigned("p-casc", ResourceType.AVATAR_CHARACTER, "c-casc")

    # 刪除資源 -> 檢查 assignments 自動 CASCADE 刪除
    resources.unregister(ResourceType.AVATAR_CHARACTER, "c-casc")
    assert not assignments.is_assigned("p-casc", ResourceType.AVATAR_CHARACTER, "c-casc")

    # 再次指派後刪除專案
    resources.upsert_system_resource(resource_type=ResourceType.AVATAR_CHARACTER, resource_id="c-casc-2", metadata={})
    assignments.assign(project_id="p-casc", resource_type=ResourceType.AVATAR_CHARACTER, resource_id="c-casc-2", assigned_by=root.id)
    assert assignments.is_assigned("p-casc", ResourceType.AVATAR_CHARACTER, "c-casc-2")

    # 刪除專案
    resources.unregister(ResourceType.PROJECT, "p-casc")
    assert not assignments.is_assigned("p-casc", ResourceType.AVATAR_CHARACTER, "c-casc-2")


def test_upload_with_project_id_by_scoped_admin(env, monkeypatch):
    """受限 admin 帶 project_id 上傳 200，無管理權限之專案 403。"""
    from io import BytesIO
    from app.routes import backgrounds as background_routes

    monkeypatch.setattr(
        background_routes.get_store(),
        "create_background",
        lambda background_id, label, image_bytes, filename: {
            "background_id": background_id,
            "label": label,
        },
    )

    # admin 有 proj-1 權限 -> 帶 project_id=proj-1 上傳成功 (200)
    files = {"image": ("bg.png", BytesIO(b"\x89PNG\r\n\x1a\nfake"), "image/png")}
    data = {"background_id": "bg-new-proj1", "label": "Proj1 BG", "project_id": "proj-1"}
    r = env.client.post(
        "/api/v1/backgrounds",
        data=data,
        files=files,
        headers=_headers(env, env.admin),
    )
    assert r.status_code == 200
    rec = env.runtime.resources.get(ResourceType.AVATAR_BACKGROUND, "bg-new-proj1")
    assert rec is not None
    assert rec.owner_project_id == "proj-1"
    assert rec.visibility is ResourceVisibility.PROJECT

    # admin 沒有 proj-2 權限 -> 帶 project_id=proj-2 上傳失敗 (403)
    files2 = {"image": ("bg.png", BytesIO(b"\x89PNG\r\n\x1a\nfake"), "image/png")}
    data2 = {"background_id": "bg-new-proj2", "label": "Proj2 BG", "project_id": "proj-2"}
    r2 = env.client.post(
        "/api/v1/backgrounds",
        data=data2,
        files=files2,
        headers=_headers(env, env.admin),
    )
    assert r2.status_code == 403


def test_list_resources_with_unauthorized_project_returns_404(env):
    """列表 ?project_id= 非成員 404（avatar / backgrounds / mascots）。"""
    # member 只有 proj-1 權限，查詢未授權的 proj-2 一律回 404
    for endpoint in ["/api/v1/avatar", "/api/v1/backgrounds", "/api/v1/avatar/mascots"]:
        r = env.client.get(
            endpoint,
            params={"project_id": "proj-2"},
            headers=_headers(env, env.member),
        )
        assert r.status_code == 404, f"{endpoint} should return 404 for unauthorized project"

    # member 查詢授權的 proj-1 回 200
    for endpoint in ["/api/v1/avatar", "/api/v1/backgrounds", "/api/v1/avatar/mascots"]:
        r = env.client.get(
            endpoint,
            params={"project_id": "proj-1"},
            headers=_headers(env, env.member),
        )
        assert r.status_code == 200, f"{endpoint} should return 200 for member project"


def test_static_assets_authorization_matrix(env):
    """靜態檔授權矩陣：成員放行、非成員 403、Embed 只限綁定專案、被指派專案的成員放行。"""
    # 準備靜態檔案
    bg_dir = env.tmp_path / "backgrounds" / "bg-proj-1"
    bg_dir.mkdir(parents=True, exist_ok=True)
    file_path = bg_dir / "default.png"
    file_path.write_bytes(b"\x89PNG\r\n\x1a\ntest")

    # 1. 成員訪問所屬專案的專案專屬資源放行 200
    r_member = env.client.get(
        "/static/backgrounds/bg-proj-1/default.png",
        headers=_headers(env, env.member),
    )
    assert r_member.status_code == 200

    # 2. 非成員訪問專案專屬資源 403
    r_non = env.client.get(
        "/static/backgrounds/bg-proj-1/default.png",
        headers=_headers(env, env.non_member),
    )
    assert r_non.status_code == 403

    # 3. 被指派專案的成員放行：建立專案資源 bg-other-proj 隸屬 proj-2，但被指派給 proj-1
    env.runtime.resources.register(
        resource_type=ResourceType.AVATAR_BACKGROUND,
        resource_id="bg-assigned-1",
        owner_user_id=None,
        visibility=ResourceVisibility.PROJECT,
        owner_project_id="proj-2",
        metadata={"label": "Assigned Bg"},
    )
    env.runtime.project_resource_assignments.assign(
        project_id="proj-1",
        resource_type=ResourceType.AVATAR_BACKGROUND,
        resource_id="bg-assigned-1",
        assigned_by=env.root.id,
    )
    assigned_dir = env.tmp_path / "backgrounds" / "bg-assigned-1"
    assigned_dir.mkdir(parents=True, exist_ok=True)
    (assigned_dir / "default.png").write_bytes(b"\x89PNG\r\n\x1a\nassigned")

    # member (只被 grant proj-1) 訪問被指派給 proj-1 的資源放行 200
    r_assigned = env.client.get(
        "/static/backgrounds/bg-assigned-1/default.png",
        headers=_headers(env, env.member),
    )
    assert r_assigned.status_code == 200

    # non_member 訪問仍 403
    assert env.client.get(
        "/static/backgrounds/bg-assigned-1/default.png",
        headers=_headers(env, env.non_member),
    ).status_code == 403

    # 4. Embed key 授權：靜態資源路由限 /static/characters/{char_id}/...，且只看金鑰綁定之專案
    # 準備角色靜態檔案與資源登記
    for char_id in ["char-proj-1", "char-assigned-1", "char-p2-only"]:
        char_dir = env.tmp_path / "avatar" / char_id
        char_dir.mkdir(parents=True, exist_ok=True)
        (char_dir / "default.png").write_bytes(b"\x89PNG\r\n\x1a\nchar")

    for char_id, owner_proj in [
        ("char-assigned-1", "proj-2"),
        ("char-p2-only", "proj-2"),
    ]:
        env.runtime.resources.register(
            resource_type=ResourceType.AVATAR_CHARACTER,
            resource_id=char_id,
            owner_user_id=None,
            visibility=ResourceVisibility.PROJECT,
            owner_project_id=owner_proj,
            metadata={"label": char_id},
        )
    # 指派 char-assigned-1 給 proj-1
    env.runtime.project_resource_assignments.assign(
        project_id="proj-1",
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="char-assigned-1",
        assigned_by=env.root.id,
    )

    embed_key_proj1 = env.runtime.embed_keys.create(
        label="test-key-p1",
        project_id="proj-1",
        allowed_origins=["http://localhost"],
        default_character_id="char-proj-1",
        allowed_character_ids=["char-proj-1", "char-assigned-1", "char-p2-only"],
    )
    embed_headers_p1 = {"X-Embed-Key": embed_key_proj1.key_id, "Origin": "http://localhost"}

    # 綁定 proj-1 的 Embed key 訪問 proj-1 專案角色放行 200
    assert env.client.get(
        "/static/characters/char-proj-1/default.png",
        headers=embed_headers_p1,
    ).status_code == 200

    # 綁定 proj-1 的 Embed key 訪問指派給 proj-1 的角色放行 200
    assert env.client.get(
        "/static/characters/char-assigned-1/default.png",
        headers=embed_headers_p1,
    ).status_code == 200

    # 綁定 proj-1 的 Embed key 訪問 proj-2 專案角色回 403
    assert env.client.get(
        "/static/characters/char-p2-only/default.png",
        headers=embed_headers_p1,
    ).status_code == 403


def test_default_voice_id_base_behavior_and_embed_project_default(env):
    """_default_voice_id 與 base 行為一致，Embed 採用 policy 的 default_tts_voice。"""
    from app.auth.dependencies import AuthTransport, CurrentAccount
    from app.auth.models import ProjectPolicyRecord
    from app.auth.voice_access import _default_voice_id, resolve_tts_voice

    curr_member = CurrentAccount(user=env.member, transport=AuthTransport.BEARER)

    # 1. 無 project/assigned 介入時，維持第一期原邏輯：
    # 沒有專案限制時直接用帳號預設
    voice_base = _default_voice_id(
        curr_member, env.runtime, None, account_default="voice-global-1"
    )
    assert voice_base == "voice-global-1"

    # 有專案限制且帳號預設在白名單內
    policy_allowed = ProjectPolicyRecord(
        project_id="proj-1",
        default_tts_voice="",
        allowed_tts_voices=("voice-global-1",),
    )
    assert _default_voice_id(
        curr_member, env.runtime, policy_allowed, account_default="voice-global-1"
    ) == "voice-global-1"

    # 有專案限制但帳號預設被排除 -> 退回清單第一個可用聲音
    env.runtime.resources.upsert_system_resource(
        resource_type=ResourceType.CUSTOM_VOICE, resource_id="voice-global-2", metadata={"provider": "indextts"}
    )
    user_two = env.runtime.users.create(
        username="user-two-voices",
        password_hash="unused",
        role=AccountRole.USER,
        created_by=env.root.id,
        grants=[
            (ResourceType.PROJECT, "proj-1"),
            (ResourceType.AVATAR_CHARACTER, "char-global-1"),
            (ResourceType.CUSTOM_VOICE, "voice-global-1"),
            (ResourceType.CUSTOM_VOICE, "voice-global-2"),
        ],
        defaults=("proj-1", "char-global-1", "indextts", "voice-global-1"),
    )
    curr_two = CurrentAccount(user=user_two, transport=AuthTransport.BEARER)
    policy_excluded = ProjectPolicyRecord(
        project_id="proj-1",
        default_tts_voice="",
        allowed_tts_voices=("voice-global-2",),
    )
    assert _default_voice_id(
        curr_two, env.runtime, policy_excluded, account_default="voice-global-1"
    ) == "voice-global-2"

    # 2. Embed key 採用 default_tts_voice：
    key = env.runtime.embed_keys.create(
        label="embed-tts-test",
        project_id="proj-1",
        allowed_origins=["http://localhost"],
    )
    curr_embed = CurrentAccount(user=env.member, transport=AuthTransport.EMBED_KEY, embed_key=key)
    env.runtime.project_policies.replace(
        project_id="proj-1",
        default_tts_voice="voice-global-1",
        allowed_tts_voices=("voice-global-1",),
        updated_by=env.root.id,
    )
    # resolve_tts_voice 未指定聲音時，直接採用專案 default_tts_voice
    resolved = resolve_tts_voice(
        curr_embed,
        env.runtime,
        requested_provider="",
        requested_voice="",
        project_id="proj-1",
    )
    assert resolved is not None
    assert resolved.resource_id == "voice-global-1"


def test_duplicate_upload_409_conflict_and_reupload_update(env, monkeypatch):
    """409 重複上傳三種情況：全域衝突 409、跨專案衝突 409、同專案重傳更新 200。"""
    import json
    from io import BytesIO
    from app.routes import backgrounds as background_routes

    updated_labels = []
    monkeypatch.setattr(
        background_routes.get_store(),
        "create_background",
        lambda background_id, label, image_bytes, filename: updated_labels.append(label) or {
            "background_id": background_id,
            "label": label,
        },
    )

    # 情況 1：與現有全域資源同名上傳 -> 409
    files = {"image": ("bg.png", BytesIO(b"\x89PNG\r\n\x1a\nfake"), "image/png")}
    r_global = env.client.post(
        "/api/v1/backgrounds",
        data={"background_id": "bg-global-1", "label": "Dup Global", "project_id": "proj-1"},
        files=files,
        headers=_headers(env, env.root),
    )
    assert r_global.status_code == 409
    assert "全域資源" in r_global.json()["detail"]

    # 情況 2：與其他專案的專案資源同名上傳 -> 409
    # bg-proj-1 屬於 proj-1，嘗試上傳到 proj-2
    files2 = {"image": ("bg.png", BytesIO(b"\x89PNG\r\n\x1a\nfake"), "image/png")}
    r_other = env.client.post(
        "/api/v1/backgrounds",
        data={"background_id": "bg-proj-1", "label": "Cross Proj", "project_id": "proj-2"},
        files=files2,
        headers=_headers(env, env.root),
    )
    assert r_other.status_code == 409
    assert "其他專案" in r_other.json()["detail"]

    # 情況 3：同一專案重複上傳同一資源 -> 200 成功更新 metadata
    files3 = {"image": ("bg.png", BytesIO(b"\x89PNG\r\n\x1a\nfake"), "image/png")}
    r_same = env.client.post(
        "/api/v1/backgrounds",
        data={"background_id": "bg-proj-1", "label": "Updated Label", "project_id": "proj-1"},
        files=files3,
        headers=_headers(env, env.root),
    )
    assert r_same.status_code == 200
    rec = env.runtime.resources.get(ResourceType.AVATAR_BACKGROUND, "bg-proj-1")
    assert rec is not None
    assert json.loads(rec.metadata_json).get("label") == "Updated Label"


def test_unscoped_avatar_list_shows_project_characters_only_to_root(env, monkeypatch):
    """後台資源管理頁不帶專案：ROOT 要看到各專案的專屬人物並知道屬於哪個專案。"""
    from app.routes import avatar as avatar_routes

    monkeypatch.setattr(
        avatar_routes.get_store(),
        "list_characters",
        lambda: [
            {"char_id": "char-global-1", "label": "Global Char 1"},
            {"char_id": "char-proj-1", "label": "Project Char 1"},
        ],
    )

    root = env.client.get("/api/v1/avatar", headers=_headers(env, env.root)).json()
    root_chars = {c["char_id"]: c for c in root["characters"]}
    assert root_chars["char-proj-1"]["source"] == "project"
    assert root_chars["char-proj-1"]["owner_project_id"] == "proj-1"
    assert root_chars["char-global-1"]["source"] == "grant"
    assert root_chars["char-global-1"]["owner_project_id"] is None

    member = env.client.get("/api/v1/avatar", headers=_headers(env, env.member)).json()
    assert "char-proj-1" not in {c["char_id"] for c in member["characters"]}


def test_old_grant_does_not_open_a_resource_moved_into_another_project(env):
    # 2026-10-16：全域人物改成 ESG 專屬後，醫院帳號身上留著以前的直接授權，
    # 選單看不到了，直接輸入素材網址卻還是 200。專案專屬資源只看專案。
    char_dir = env.tmp_path / "avatar" / "char-global-1"
    char_dir.mkdir(parents=True, exist_ok=True)
    (char_dir / "01.webm").write_bytes(b"webm")
    url = "/static/characters/char-global-1/01.webm"
    assert env.client.get(url, headers=_headers(env, env.member)).status_code == 200

    with env.runtime.database.transaction(write=True) as connection:
        connection.execute(
            "UPDATE resources SET visibility = 'project', owner_project_id = 'proj-2'"
            " WHERE resource_type = 'avatar_character' AND resource_id = 'char-global-1'"
        )

    assert env.client.get(url, headers=_headers(env, env.member)).status_code == 403

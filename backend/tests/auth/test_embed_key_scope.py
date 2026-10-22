"""Embed keys follow the administrator's scope.

受限管理員只看得到、只管得了自己範圍內專案的 Embed 金鑰；範圍外的金鑰與專案
一律當作不存在（404），ROOT 與沒設範圍的管理員照舊管全部。
"""

from __future__ import annotations

import pytest
from app.auth.embed_key_routes import router
from app.auth.middleware import FailClosedAuthMiddleware
from app.auth.models import AccountRole, ResourceType
from app.auth.runtime import build_auth_runtime, get_auth_runtime
from app.config import TTSRouterConfig
from fastapi import FastAPI
from fastapi.testclient import TestClient

ORIGIN = "https://partner.example"


@pytest.fixture
def setup(tmp_path):
    runtime = build_auth_runtime(
        TTSRouterConfig(
            _env_file=None,
            env="dev",
            session_jwt_secret="test-only-embed-key-scope-secret-32",
            auth_database_path=str(tmp_path / "auth.db"),
        )
    )
    root = runtime.users.create_root(username="ai360", password_hash="unused")
    scoped = runtime.users.create(
        username="scoped", password_hash="unused", role=AccountRole.ADMIN, created_by=root.id
    )
    unscoped = runtime.users.create(
        username="unscoped", password_hash="unused", role=AccountRole.ADMIN, created_by=root.id
    )
    for project_id in ("inside", "outside"):
        runtime.resources.upsert_system_resource(
            resource_type=ResourceType.PROJECT, resource_id=project_id
        )
    runtime.admin_scopes.replace(
        admin_user_id=scoped.id,
        updated_by=root.id,
        scoped=True,
        resources=[(ResourceType.PROJECT, "inside")],
    )
    keys = {
        project_id: runtime.embed_keys.create(
            label=project_id,
            project_id=project_id,
            allowed_origins=[ORIGIN],
            created_by=root.id,
        ).key_id
        for project_id in ("inside", "outside")
    }
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(FailClosedAuthMiddleware, runtime=runtime)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield runtime, client, {"root": root, "scoped": scoped, "unscoped": unscoped}, keys


def _headers(runtime, user):
    return {"Authorization": f"Bearer {runtime.tokens.issue(user)}"}


def _listed_projects(client, headers):
    response = client.get("/api/v1/embed-keys", headers=headers)
    assert response.status_code == 200
    return sorted(key["project_id"] for key in response.json()["embed_keys"])


def test_scoped_admin_lists_only_keys_inside_its_scope(setup):
    runtime, client, users, _keys = setup

    assert _listed_projects(client, _headers(runtime, users["scoped"])) == ["inside"]
    assert _listed_projects(client, _headers(runtime, users["root"])) == ["inside", "outside"]
    assert _listed_projects(client, _headers(runtime, users["unscoped"])) == ["inside", "outside"]


def test_scoped_admin_cannot_create_a_key_for_a_project_outside_its_scope(setup):
    runtime, client, users, _keys = setup
    headers = _headers(runtime, users["scoped"])

    outside = client.post(
        "/api/v1/embed-keys",
        headers=headers,
        json={"project_id": "outside", "allowed_origins": [ORIGIN]},
    )
    inside = client.post(
        "/api/v1/embed-keys",
        headers=headers,
        json={"project_id": "inside", "allowed_origins": [ORIGIN]},
    )

    assert outside.status_code == 404
    assert inside.status_code == 201
    assert sorted(record.project_id for record in runtime.embed_keys.list_all()) == [
        "inside",
        "inside",
        "outside",
    ]


def test_scoped_admin_cannot_change_or_delete_a_key_outside_its_scope(setup):
    runtime, client, users, keys = setup
    headers = _headers(runtime, users["scoped"])

    patched = client.patch(
        f"/api/v1/embed-keys/{keys['outside']}",
        headers=headers,
        json={"allowed_origins": ["https://attacker.example"]},
    )
    deleted = client.delete(f"/api/v1/embed-keys/{keys['outside']}", headers=headers)

    assert patched.status_code == 404
    assert deleted.status_code == 404
    untouched = runtime.embed_keys.get(keys["outside"])
    assert untouched is not None
    assert list(untouched.allowed_origins) == [ORIGIN]


def test_scoped_admin_still_manages_keys_inside_its_scope(setup):
    runtime, client, users, keys = setup
    headers = _headers(runtime, users["scoped"])

    patched = client.patch(
        f"/api/v1/embed-keys/{keys['inside']}", headers=headers, json={"label": "renamed"}
    )
    deleted = client.delete(f"/api/v1/embed-keys/{keys['inside']}", headers=headers)

    assert patched.status_code == 200
    assert patched.json()["label"] == "renamed"
    assert deleted.status_code == 200
    assert runtime.embed_keys.get(keys["inside"]) is None


def test_root_manages_keys_in_any_project(setup):
    runtime, client, users, keys = setup
    headers = _headers(runtime, users["root"])

    assert client.delete(f"/api/v1/embed-keys/{keys['outside']}", headers=headers).status_code == 200


def test_scoped_admin_can_manage_a_key_created_with_padded_project_id(setup):
    # 範圍比對用的是存下來的 project_id；儲存時去空白（repository 負責），
    # 受限管理員才看得到自己用帶空白的 ID 建的金鑰。
    runtime, client, users, _keys = setup
    headers = _headers(runtime, users["scoped"])

    created = client.post(
        "/api/v1/embed-keys",
        headers=headers,
        json={"project_id": "  inside  ", "allowed_origins": [ORIGIN]},
    )

    assert created.status_code == 201
    assert created.json()["project_id"] == "inside"
    assert _listed_projects(client, headers) == ["inside", "inside"]

"""Exercise account and project authorization through the registered HTTP routes."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

from app import brain_proxy, project_routes
from app.auth import api_key_routes
from app.auth.middleware import FailClosedAuthMiddleware
from app.auth.models import AccountRole, AccountType, ResourceType
from app.auth.routes import auth_router, users_router
from app.auth.runtime import get_auth_runtime
from app.gateway import asr_stream
from app.gateway import routes as gateway_routes
from app.gateway import websocket as websocket_routes


_PASSWORD = "user-password"
_PROJECT = "project-a"
_UNGRANTED = "project-a-extra"
_OTHER = "project-b"
_HEADERS = {"Origin": "http://testserver"}


def _access(
    project: str = _PROJECT,
    *,
    knowledge: bool | None = None,
    settings: bool = False,
    portal: bool = True,
) -> dict:
    grants = {
        "projects": [project],
        "avatar_characters": ["character-a"],
        "custom_voices": ["voice-a"],
    }
    if knowledge is not None:
        grants["project_permissions"] = {
            project: {"edit_knowledge": knowledge, "edit_settings": settings},
        }
    return {
        "grants": grants,
        "defaults": {
            "project_id": project,
            "character_id": "character-a",
            "voice_provider": "indextts",
            "voice_id": "voice-a",
        },
        "admin_portal_access": portal,
    }


def _project(project_id: str) -> dict:
    return {
        "project_id": project_id,
        "label": project_id,
        "is_default": False,
        "project_root": f"/data/private/{project_id}",
        "has_session_db": True,
        "has_lancedb": True,
    }


@pytest.fixture()
def env(monkeypatch):
    runtime = get_auth_runtime()
    root = runtime.users.create_root(username="ai360", password_hash="unused")
    admin = runtime.users.create(
        username="operator", password_hash="unused",
        role=AccountRole.ADMIN, created_by=root.id,
    )
    other_admin = runtime.users.create(
        username="other-operator", password_hash="unused",
        role=AccountRole.ADMIN, created_by=root.id,
    )
    projects = [_project(pid) for pid in (_PROJECT, _UNGRANTED, _OTHER)]
    for resource_type, resource_id in (
        (ResourceType.PROJECT, _PROJECT),
        (ResourceType.PROJECT, _UNGRANTED),
        (ResourceType.PROJECT, _OTHER),
        (ResourceType.AVATAR_CHARACTER, "character-a"),
        (ResourceType.CUSTOM_VOICE, "voice-a"),
    ):
        runtime.resources.upsert_system_resource(
            resource_type=resource_type,
            resource_id=resource_id,
            metadata={"provider": "indextts"} if resource_id == "voice-a" else {},
        )

    received: list[httpx.Request] = []

    async def brain(request: httpx.Request) -> httpx.Response:
        await request.aread()
        received.append(request)
        path = request.url.path
        if path == "/brain/personas/soul" and request.method == "GET":
            return httpx.Response(200, json={"content": "原始人設"})
        if path == "/brain/projects":
            if request.method == "POST":
                data = json.loads(request.content)
                assert data == {"label": "新知識庫"}
                return httpx.Response(200, json=_project("new-project"))
            return httpx.Response(200, json={"projects": projects, "project_count": len(projects)})
        if path.startswith("/brain/projects/"):
            return httpx.Response(200, json=_project(path.split("/")[-1]))
        return httpx.Response(200, json={"status": "ok"})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(brain))
    monkeypatch.setattr(brain_proxy._http, "get", lambda: upstream)
    app = FastAPI()
    for router in (
        auth_router, users_router, api_key_routes.router,
        gateway_routes.router, project_routes.router, asr_stream.router,
        websocket_routes.router, brain_proxy.router,
    ):
        app.include_router(router)
    app.add_middleware(FailClosedAuthMiddleware, runtime=runtime)
    client = TestClient(app)

    def headers(user_id: str) -> dict[str, str]:
        user = runtime.users.get_by_id(user_id)
        assert user is not None
        return {**_HEADERS, "Authorization": f"Bearer {runtime.tokens.issue(user)}"}

    def create(username: str, *, actor_id=root.id, **fields):
        return client.post(
            "/api/v1/users",
            headers=headers(actor_id),
            json={"username": username, "password": _PASSWORD, **fields},
        )

    return SimpleNamespace(
        client=client, runtime=runtime, root=root, admin=admin,
        other_admin=other_admin, headers=headers, create=create, received=received,
    )


def _set_project_vendor(env, project_id: str, vendor_name: str | None):
    return env.client.patch(
        f"/api/v1/projects/{project_id}/vendor",
        headers=env.headers(env.root.id),
        json={"vendor_name": vendor_name},
    )


def _assign_vendors(env) -> None:
    for project, vendor in ((_PROJECT, "甲商"), (_UNGRANTED, "甲商"), (_OTHER, "乙商")):
        assert _set_project_vendor(env, project, vendor).status_code == 200


@pytest.mark.parametrize(
    ("knowledge", "settings"),
    [(True, False), (False, True), (False, False), (True, True)],
    ids=["knowledge-editor", "settings-editor", "reader", "both-editor"],
)
def test_explicit_project_permissions_at_proxy_and_direct_routes(env, knowledge, settings):
    created = env.create(
        "editor", access=_access(knowledge=knowledge, settings=settings),
    )
    assert created.status_code == 201, created.text
    account = created.json()
    assert account["grants"]["project_permissions"] == {
        _PROJECT: {"edit_knowledge": knowledge, "edit_settings": settings},
    }
    legacy_update = env.client.put(
        f"/api/v1/users/{account['id']}/access",
        headers=env.headers(env.root.id),
        json=_access(),
    )
    assert legacy_update.status_code == 200, legacy_update.text
    assert legacy_update.json()["grants"]["project_permissions"] == account["grants"]["project_permissions"]
    headers = env.headers(account["id"])
    for method, route, payload, allowed in (
        ("PUT", "knowledge/document", {"path": "knowledge/a.md", "content": "a"}, knowledge),
        ("PUT", "knowledge/document", {"path": "SOUL.md", "content": "a"}, knowledge),
        ("PUT", "knowledge/document", {"path": "MEMORY.md", "content": "a"}, settings),
        (
            "POST", "knowledge/renormalize/apply",
            {"path": "knowledge/a.md", "content": "a"}, knowledge,
        ),
        (
            "POST", "knowledge/renormalize/apply",
            {"path": "MEMORY.md", "content": "a"}, settings,
        ),
        (
            "POST", "knowledge/move",
            {"source_path": "knowledge/a.md", "target_path": "knowledge/b.md"}, knowledge,
        ),
        (
            "POST", "knowledge/move",
            {"source_path": "knowledge/a.md", "target_path": "MEMORY.md"},
            knowledge and settings,
        ),
        ("POST", "personas", {"persona_id": "new-persona"}, knowledge),
        ("PUT", "knowledge/settings", {"reply_language": "zh"}, knowledge),
        ("POST", "memories/maintain", {}, settings),
        ("PATCH", "tools/example", {}, settings),
        ("PATCH", "skills/sample/toggle?scope=project", {}, settings),
        ("DELETE", "sessions/s1", None, settings),
        ("POST", "sessions/batch-delete", {"session_ids": ["s1"]}, settings),
    ):
        received_before = len(env.received)
        separator = "&" if "?" in route else "?"
        response = env.client.request(
            method, f"/api/v1/{route}{separator}project_id={_PROJECT}",
            headers=headers, json=payload,
        )
        assert response.status_code == (200 if allowed else 403), response.text
        assert len(env.received) == received_before + int(allowed)

    upload = env.client.post(
        "/api/v1/knowledge/raw/upload",
        headers=headers,
        data={"project_id": _PROJECT},
        files={"files": ("example.md", b"# Notes", "text/markdown")},
    )
    assert upload.status_code == (200 if knowledge else 404), upload.text
    policy = env.client.get(f"/api/v1/projects/{_PROJECT}/policy", headers=headers)
    assert policy.status_code == (200 if settings else 404), policy.text


def test_project_read_allows_list_export_and_history_with_no_write_access(env):
    created = env.create("reader", access=_access(portal=False))
    assert created.status_code == 201, created.text
    headers = env.headers(created.json()["id"])
    for route, params in (
        ("sessions", {}),
        ("sessions/export", {}),
        ("chat/history", {"session_id": "s1"}),
    ):
        response = env.client.get(
            f"/api/v1/{route}", headers=headers, params={"project_id": _PROJECT, **params},
        )
        assert response.status_code == 200, response.text
        hidden = env.client.get(
            f"/api/v1/{route}", headers=headers, params={"project_id": _OTHER, **params},
        )
        assert hidden.status_code == 404
    assert env.client.delete(
        "/api/v1/sessions/s1", headers=headers, params={"project_id": _PROJECT},
    ).status_code == 403


def test_user_cannot_mint_keys_admin_can_issue_and_revoke(env):
    created = env.create("existing-user", access=_access(portal=False))
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    headers = env.headers(user_id)
    for target in ({}, {"user_id": user_id}, {"user_id": env.admin.id}):
        response = env.client.post(
            "/api/v1/api-keys", headers=headers, json={"label": "test-key", **target},
        )
        assert response.status_code == 403

    root_headers = env.headers(env.root.id)
    response = env.client.post(
        "/api/v1/api-keys", headers=root_headers,
        json={"label": "delegated", "user_id": user_id},
    )
    assert response.status_code == 201, response.text
    issued = response.json()
    key_headers = {"Authorization": f"Bearer {issued['key']}"}
    assert env.client.get(
        "/api/v1/sessions", headers=key_headers, params={"project_id": _PROJECT},
    ).status_code == 200
    assert env.client.delete(
        f"/api/v1/api-keys/{issued['key_id']}", headers=root_headers,
    ).status_code == 200
    assert env.client.get(
        "/api/v1/sessions", headers=key_headers, params={"project_id": _PROJECT},
    ).status_code == 401


def test_vendor_management_flag_is_root_only_and_limited_to_vendor_users(env):
    _assign_vendors(env)
    created = env.create("vendor-account", vendor_name="  甲商  ", access=_access())
    assert created.status_code == 201, created.text
    assert created.json()["vendor_name"] == "甲商"
    target_id = created.json()["id"]
    internal = env.create("internal")
    assert internal.status_code == 201
    internal_id = internal.json()["id"]
    management = f"/api/v1/users/{env.admin.id}/account-management"
    target = f"/api/v1/users/{target_id}"
    headers = env.headers(env.admin.id)
    root_headers = env.headers(env.root.id)

    assert env.client.patch(
        management, headers=headers, json={"enabled": True},
    ).status_code == 403
    assert env.create(
        "vendor-denied", actor_id=env.admin.id, vendor_name="甲商", access=_access(),
    ).status_code == 403
    assert env.client.post(
        f"{target}/password-reset", headers=headers, json={"password": "changed-password"},
    ).status_code == 403
    listing = env.client.get("/api/v1/users", headers=headers)
    assert listing.status_code == 200, listing.text
    assert target_id not in {item["id"] for item in listing.json()}

    enabled = env.client.patch(management, headers=root_headers, json={"enabled": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["account_management_access"] is True
    headers = env.headers(env.admin.id)
    listing = env.client.get("/api/v1/users", headers=headers)
    assert listing.status_code == 200, listing.text
    assert target_id in {item["id"] for item in listing.json()}
    new_user = env.create(
        "vendor-allowed", actor_id=env.admin.id, vendor_name="甲商", access=_access(),
    )
    assert new_user.status_code == 201, new_user.text
    assert env.create(
        "invalid-admin", actor_id=env.admin.id, vendor_name="甲商", role="admin",
    ).status_code in {403, 422}
    assert env.client.patch(
        f"/api/v1/users/{target_id}/account-management", headers=root_headers,
        json={"enabled": True},
    ).status_code in {403, 422}
    assert env.client.patch(
        f"/api/v1/users/{internal_id}/vendor", headers=headers,
        json={"vendor_name": "甲商"},
    ).status_code == 403

    assert env.client.post(
        f"{target}/password-reset", headers=headers, json={"password": "changed-password"},
    ).status_code == 200
    login = env.client.post(
        "/api/v1/auth/login",
        json={"username": "vendor-account", "password": "changed-password"},
    )
    assert login.status_code == 200, login.text
    env.client.cookies.clear()
    issued = env.client.post(
        "/api/v1/api-keys", headers=headers, json={"label": "vendor-key", "user_id": target_id},
    )
    assert issued.status_code == 201, issued.text
    assert env.client.delete(
        f"/api/v1/api-keys/{issued.json()['key_id']}", headers=headers,
    ).status_code == 200
    assert env.client.patch(
        f"{target}/disabled", headers=headers, json={"disabled": True},
    ).status_code == 200
    assert env.client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    ).status_code == 401
    assert env.client.patch(
        f"{target}/disabled", headers=headers, json={"disabled": False},
    ).status_code == 200
    temporary = env.runtime.users.create(
        username="temporary", password_hash="unused", role=AccountRole.USER,
        account_type=AccountType.TEMPORARY, created_by=env.other_admin.id,
    )
    for other in (internal_id, env.other_admin.id, env.root.id, temporary.id):
        assert env.client.post(
            f"/api/v1/users/{other}/password-reset", headers=headers,
            json={"password": "changed-password"},
        ).status_code == 403
        assert env.client.patch(
            f"/api/v1/users/{other}/disabled", headers=headers, json={"disabled": True},
        ).status_code == 403
        assert env.client.post(
            "/api/v1/api-keys", headers=headers, json={"label": "forbidden", "user_id": other},
        ).status_code == 403
    assert env.client.post(f"{target}/revoke", headers=headers).status_code == 403
    assert env.client.delete(target, headers=headers).status_code == 403
    assert env.client.put(f"{target}/access", headers=headers, json=_access()).status_code == 403
    assert env.client.patch(f"{target}/role", headers=headers, json={"role": "admin"}).status_code == 403

    outside = env.create("vendor-outside", vendor_name="乙商", access=_access(_OTHER))
    assert outside.status_code == 201, outside.text
    outside_id = outside.json()["id"]
    env.runtime.admin_scopes.replace(
        admin_user_id=env.admin.id,
        updated_by=env.root.id,
        scoped=True,
        resources=[
            (ResourceType.PROJECT, _PROJECT),
            (ResourceType.AVATAR_CHARACTER, "character-a"),
            (ResourceType.CUSTOM_VOICE, "voice-a"),
        ],
    )
    records = env.client.get("/api/v1/users", headers=headers)
    assert records.status_code == 200, records.text
    visible_ids = {item["id"] for item in records.json()}
    assert target_id in visible_ids
    assert outside_id not in visible_ids
    assert env.client.post(
        f"/api/v1/users/{outside_id}/password-reset", headers=headers,
        json={"password": "changed-password"},
    ).status_code == 403
    assert env.client.patch(
        f"/api/v1/users/{outside_id}/disabled", headers=headers, json={"disabled": True},
    ).status_code == 403
    assert env.client.post(
        "/api/v1/api-keys", headers=headers,
        json={"label": "outside-key", "user_id": outside_id},
    ).status_code == 403

    revoked = env.client.patch(management, headers=root_headers, json={"enabled": False})
    assert revoked.status_code == 200, revoked.text
    assert env.client.post(
        f"{target}/password-reset", headers=env.headers(env.admin.id),
        json={"password": "changed-password"},
    ).status_code == 403


def test_vendor_assignment_enforced_by_grants_and_live_project_access(env):
    _assign_vendors(env)
    root_headers = env.headers(env.root.id)
    created = env.create("member", vendor_name="甲商", access=_access())
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    headers = env.headers(user_id)
    profile = env.client.get("/api/v1/auth/me", headers=headers)
    assert profile.status_code == 200, profile.text
    assert profile.json()["vendor_name"] == "甲商"
    assert {"created_by", "account_management_access", "password_hash"}.isdisjoint(profile.json())
    assert env.client.get("/api/v1/api-keys", headers=headers).status_code == 403

    cross_vendor = env.create("wrong-vendor", vendor_name="甲商", access=_access(_OTHER))
    assert cross_vendor.status_code == 422, cross_vendor.text
    assert env.runtime.users.get_by_username("wrong-vendor") is None
    update = env.client.put(
        f"/api/v1/users/{user_id}/access", headers=root_headers, json=_access(_OTHER),
    )
    assert update.status_code == 422, update.text

    listing = env.client.get("/api/v1/projects", headers=headers)
    assert listing.status_code == 200, listing.text
    assert listing.json()["project_count"] == 1
    summary, = listing.json()["projects"]
    assert summary["project_id"] == _PROJECT
    details = env.client.get(f"/api/v1/projects/{_PROJECT}", headers=headers)
    assert details.status_code == 200, details.text
    for payload in (summary, details.json()):
        assert {"project_root", "has_session_db", "has_lancedb"}.isdisjoint(payload)
    internal_details = env.client.get(f"/api/v1/projects/{_PROJECT}", headers=root_headers)
    assert internal_details.json()["project_root"] == f"/data/private/{_PROJECT}"
    for hidden_id in (_OTHER, _UNGRANTED):
        assert env.client.get(f"/api/v1/projects/{hidden_id}", headers=headers).status_code == 404
        assert env.client.get(
            "/api/v1/knowledge/base/documents", headers=headers, params={"project_id": hidden_id},
        ).status_code == 404
    assert env.client.patch(
        f"/api/v1/projects/{_PROJECT}/vendor", headers=headers, json={"vendor_name": "乙商"},
    ).status_code == 403

    assert _set_project_vendor(env, _PROJECT, "乙商").status_code == 200
    assert env.client.get("/api/v1/projects", headers=headers).json()["projects"] == []
    assert env.client.get(
        "/api/v1/knowledge/base/documents", headers=headers, params={"project_id": _PROJECT},
    ).status_code == 404
    assert env.create("inside", access=_access(_OTHER)).status_code == 201

    moved = env.client.patch(
        f"/api/v1/users/{user_id}/vendor", headers=root_headers, json={"vendor_name": " 乙商 "},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["vendor_name"] == "乙商"
    forbidden_settings = env.client.put(
        f"/api/v1/users/{user_id}/access", headers=root_headers,
        json=_access(knowledge=True, settings=True),
    )
    assert forbidden_settings.status_code == 422, forbidden_settings.text
    allowed_knowledge = env.client.put(
        f"/api/v1/users/{user_id}/access", headers=root_headers,
        json=_access(knowledge=True),
    )
    assert allowed_knowledge.status_code == 200, allowed_knowledge.text
    new_headers = env.headers(user_id)
    assert env.client.put(
        "/api/v1/knowledge/base/document", headers=new_headers,
        json={"project_id": _PROJECT, "path": "knowledge/public.md", "content": "public"},
    ).status_code == 200
    assert env.client.delete(
        "/api/v1/sessions/s1", headers=new_headers, params={"project_id": _PROJECT},
    ).status_code == 403


def test_project_creation_persists_vendor_without_forwarding_it_to_brain(env):
    response = env.client.post(
        "/api/v1/projects", headers=env.headers(env.admin.id),
        json={"label": "新知識庫", "vendor_name": " 甲商 "},
    )
    assert response.status_code == 200, response.text
    assert response.json()["vendor_name"] == "甲商"
    response = env.client.get(
        "/api/v1/projects/new-project", headers=env.headers(env.root.id),
    )
    assert response.status_code == 200, response.text
    assert response.json()["vendor_name"] == "甲商"



def test_vendor_asr_websocket_requires_a_granted_project(env, monkeypatch):
    _assign_vendors(env)
    env.runtime.resources.upsert_system_resource(
        resource_type=ResourceType.ASR_ENGINE, resource_id="r2t2-live",
    )
    access = _access()
    access["grants"]["asr_engines"] = ["r2t2-live"]
    account = env.create("vendor-voice", vendor_name="甲商", access=access)
    assert account.status_code == 201, account.text
    headers = env.headers(account.json()["id"])
    relayed_projects = []

    async def relay(websocket, current, project_id, endpoint, count_audio, routes):
        relayed_projects.append(project_id)
        await websocket.send_json({"type": "ready"})

    async def project_routes(*_args):
        return ["zh"]

    monkeypatch.setattr(asr_stream, "_project_routes", project_routes)
    monkeypatch.setattr(asr_stream, "_relay_r2t2", relay)
    monkeypatch.setattr(
        asr_stream, "_r2t2_stream_endpoint", lambda *_args: ("ws://testserver", ""),
    )
    monkeypatch.setattr(asr_stream, "record_usage_event", lambda **_event: None)
    with env.client.websocket_connect(
        f"/api/v1/asr/stream?project_id={_PROJECT}&engine=r2t2-live",
        headers=headers,
    ) as stream:
        assert stream.receive_json() == {"type": "ready"}

    for project_id in (_UNGRANTED, _OTHER):
        with env.client.websocket_connect(
            f"/api/v1/asr/stream?project_id={project_id}&engine=r2t2-live",
            headers=headers,
        ) as stream:
            assert stream.receive_json() == {"type": "error", "code": "not_allowed"}
    assert relayed_projects == [_PROJECT]


@pytest.fixture()
def vendor_accounts(env):
    _assign_vendors(env)
    accounts = {}
    for name, fields in (
        ("vendor-editor", {"vendor_name": "甲商", "access": _access(knowledge=True)}),
        ("vendor-reader", {"vendor_name": "甲商", "access": _access(knowledge=False)}),
        ("internal-editor", {"access": _access(knowledge=True, settings=True)}),
    ):
        result = env.create(name, **fields)
        assert result.status_code == 201
        accounts[name] = result.json()["id"]
    return accounts


def test_vendor_soul_reads_and_writes_are_bound_to_project(env, vendor_accounts):
    route = "/api/v1/personas/soul"
    editor = env.headers(vendor_accounts["vendor-editor"])
    reader = env.headers(vendor_accounts["vendor-reader"])
    for persona_id in ("default", "support"):
        params = {"project_id": _PROJECT, "persona_id": persona_id}
        response = env.client.get(route, params=params, headers=editor)
        assert response.json() == {"content": "原始人設"}
        request = env.received[-1]
        assert request.url.path == "/brain/personas/soul"
        assert request.headers["X-OpenVMan-Vendor"] == "1"
        assert dict(request.url.params) == params
        assert env.client.get(route, params=params, headers=reader).status_code == 200
        data = {**params, "content": "新人設"}
        assert env.client.put(route, json=data, headers=editor).json() == {"status": "ok"}
        assert json.loads(env.received[-1].content) == data
        assert env.client.put(route, json=data, headers=reader).status_code == 403
    before = len(env.received)
    for project in (_UNGRANTED, _OTHER):
        params = {"project_id": project, "persona_id": "default"}
        assert env.client.get(route, params=params, headers=editor).status_code == 404
        assert env.client.put(route, json={**params, "content": "x"}, headers=editor).status_code == 404
    assert len(env.received) == before


@pytest.mark.parametrize("path", [
    "SOUL.md", "AGENTS.md", "TOOLS.md", "MEMORY.md", "IDENTITY.md",
    ".learnings/LEARNINGS.md", "personas/support/AGENTS.md",
])
def test_vendor_cannot_read_or_write_core_files_through_document_apis(env, vendor_accounts, path):
    headers = env.headers(vendor_accounts["vendor-editor"])
    before = len(env.received)
    for route in ("knowledge/document", "knowledge/base/document"):
        read = env.client.get(
            f"/api/v1/{route}", params={"project_id": _PROJECT, "path": path}, headers=headers,
        )
        write = env.client.put(
            f"/api/v1/{route}",
            json={"project_id": _PROJECT, "path": path, "content": "blocked"}, headers=headers,
        )
        assert (read.status_code, write.status_code) == (403, 403)
    assert len(env.received) == before


@pytest.mark.parametrize(("method", "route", "payload"), [
    ("GET", "knowledge/documents", None),
    ("GET", "knowledge/document", None),
    ("PUT", "knowledge/document", {"path": "knowledge/public.md", "content": "x"}),
    ("PATCH", "knowledge/document/meta", {"path": "knowledge/public.md", "enabled": False}),
    ("DELETE", "knowledge/document", None),
    ("POST", "knowledge/move", {"source_path": "SOUL.md", "target_path": "x.md"}),
    ("POST", "knowledge/copy", {"source_path": "SOUL.md", "target_path": "x.md"}),
    ("POST", "knowledge/import", {"path": "AGENTS.md"}),
    ("POST", "knowledge/renormalize/preview", {"path": "AGENTS.md"}),
    ("POST", "knowledge/renormalize/apply", {"path": "AGENTS.md", "content": "x"}),
    ("POST", "personas/clone", {"source_persona_id": "default", "target_persona_id": "copy"}),
    ("POST", "personas/avatar", {"persona_id": "default", "avatar_char_id": None}),
    ("POST", "search", {"query": "工作區", "table": "knowledge"}),
    ("GET", "identity", None),
    ("GET", "memories", None),
    ("GET", "avatar", None),
    ("GET", "backgrounds", None),
    ("GET", "tts/providers", None),
    ("GET", "tools", None),
    ("GET", "settings/my-asr-provider", None),
    ("GET", "settings/model-providers", None),
    ("GET", "users", None),
    ("GET", "embed-keys", None),
    ("GET", "usage/summary", None),
    ("GET", "health/detail", None),
    ("GET", "metrics", None),
    ("GET", "knowledge/graph", None),
    ("GET", "knowledge/graph/html", None),
    ("GET", f"projects/{_PROJECT}/policy", None),
])
def test_vendor_hidden_api_is_denied_before_upstream(env, vendor_accounts, method, route, payload):
    before = len(env.received)
    response = env.client.request(
        method, f"/api/v1/{route}",
        params={"project_id": _PROJECT, "path": "knowledge/public.md"},
        json=payload, headers=env.headers(vendor_accounts["vendor-editor"]),
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "沒有權限使用這個功能。"}
    assert len(env.received) == before


def test_vendor_knowledge_page_is_scoped_and_internal_workspace_is_unchanged(env, vendor_accounts):
    editor = env.headers(vendor_accounts["vendor-editor"])
    for source, target in (
        ("knowledge/public.md", "AGENTS.md"),
        ("personas/default/MEMORY.md", "knowledge/public.md"),
    ):
        response = env.client.post("/api/v1/knowledge/base/move", headers=editor, json={
            "project_id": _PROJECT, "source_path": source, "target_path": target,
        })
        assert response.status_code == 403
    response = env.client.put("/api/v1/knowledge/base/document", headers=editor, json={
        "project_id": _PROJECT, "path": "knowledge/public.md", "content": "ok",
    })
    assert response.status_code == 200
    assert env.received[-1].url.path == "/brain/knowledge/document"
    params = {"project_id": _PROJECT, "path": "AGENTS.md"}
    for user_id in (env.root.id, vendor_accounts["internal-editor"]):
        headers = {**env.headers(user_id), "X-OpenVMan-Vendor": "1"}
        assert env.client.get("/api/v1/knowledge/documents", params=params, headers=headers).status_code == 200
        assert env.client.get("/api/v1/knowledge/document", params=params, headers=headers).status_code == 200
        assert env.client.put("/api/v1/knowledge/document", headers=headers, json={
            **params, "content": "internal",
        }).status_code == 200
        assert "X-OpenVMan-Vendor" not in env.received[-1].headers


def test_delegated_vendor_key_has_the_same_route_limit(env, vendor_accounts):
    response = env.client.post(
        "/api/v1/api-keys", headers=env.headers(env.root.id),
        json={"label": "vendor-integration", "user_id": vendor_accounts["vendor-editor"]},
    )
    assert response.status_code == 201
    headers = {"Authorization": f"Bearer {response.json()['key']}"}
    params = {"project_id": _PROJECT}
    assert env.client.get("/api/v1/personas/soul", headers=headers, params=params).status_code == 200
    assert env.client.get("/api/v1/personas", headers=headers, params=params).status_code == 200
    assert env.client.get("/api/v1/knowledge/documents", headers=headers, params=params).status_code == 403


@pytest.mark.parametrize("path", [" knowledge/guide.md", "knowledge/guide.md ", "knowledge/guide.md\t"])
def test_vendor_document_proxy_rejects_outer_whitespace(env, vendor_accounts, path):
    before = len(env.received)
    response = env.client.get(
        "/api/v1/knowledge/base/document",
        params={"project_id": _PROJECT, "path": path},
        headers=env.headers(vendor_accounts["vendor-editor"]),
    )
    assert response.status_code == 403, response.text
    assert len(env.received) == before


@pytest.mark.parametrize("account", ["vendor-editor", "internal-editor"])
def test_knowledge_upload_keeps_conversion_diagnostics_internal(env, vendor_accounts, monkeypatch, account):
    diagnostics = "conversion failed at http://api:8100/document for /tmp/converter/input.pdf"

    async def fail_conversion(*args, **kwargs):
        raise RuntimeError(diagnostics)

    monkeypatch.setattr(gateway_routes, "_prepare_document_upload", fail_conversion)
    response = env.client.post(
        "/api/v1/knowledge/upload", headers=env.headers(vendor_accounts[account]),
        data={"project_id": _PROJECT}, files={"files": ("input.pdf", b"test", "application/pdf")},
    )
    assert response.status_code == 500, response.text
    if account == "vendor-editor":
        assert response.json() == {"detail": "無法上傳檔案，請確認檔案後再試。"}
    else:
        assert response.json()["error"] == diagnostics


@pytest.mark.parametrize("account", ["vendor-editor", "internal-editor"])
def test_live_relay_uses_authenticated_account_for_vendor_header(env, vendor_accounts, monkeypatch, account):
    captured = []

    class BrainSocket:
        async def send(self, raw):
            if json.loads(raw)["event"] == "user_speak":
                ready.set()

        async def recv(self):
            await ready.wait()
            ready.clear()
            return json.dumps({"event": "server_stream_chunk", "text": "你好"})

        async def close(self):
            pass

    ready = asyncio.Event()

    async def connect(_url, *, additional_headers, **kwargs):
        captured.append(additional_headers)
        return BrainSocket()

    monkeypatch.setattr("app.gateway.brain_live_relay.websockets.connect", connect)
    headers = {**env.headers(vendor_accounts[account]), "X-OpenVMan-Vendor": "0" if account == "vendor-editor" else "1"}
    with env.client.websocket_connect("/api/v1/ws/vendor-test", headers=headers) as socket:
        socket.send_json({"event": "client_init", "capabilities": {"project_id": _PROJECT}})
        assert socket.receive_json()["event"] == "server_init_ack"
        socket.send_json({"event": "user_speak", "text": "你好"})
        assert socket.receive_json()["event"] == "server_stream_chunk"
    assert len(captured) == 1
    assert captured[0].get("X-OpenVMan-Vendor") == ("1" if account == "vendor-editor" else None)
    assert captured[0]["X-OpenVMan-Project-ID"] == _PROJECT


def test_vendor_live_requires_project_initialization_before_relay(env, vendor_accounts, monkeypatch):
    class FakeRelay:
        def __init__(self, _session, *, event_sink):
            self.event_sink = event_sink

        async def send_event(self, _event):
            await self.event_sink({"event": "server_stream_chunk", "text": "測試"})

        async def close(self):
            pass

    monkeypatch.setattr(websocket_routes, "BrainLiveRelay", FakeRelay)
    headers = env.headers(vendor_accounts["vendor-editor"])
    with env.client.websocket_connect("/api/v1/ws/vendor-project-test", headers=headers) as socket:
        socket.send_json({"event": "user_speak", "text": "測試"})
        with pytest.raises(WebSocketDisconnect) as exc:
            socket.receive_json()
    assert exc.value.code == 1008

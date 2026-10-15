"""Capabilities use live grants for sessions, API keys and temporary users."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient

from app import project_routes
from app.auth.middleware import FailClosedAuthMiddleware
from app.auth.models import AccountRole, ResourceType
from app.auth.runtime import get_auth_runtime
from app.auth.settings_routes import settings_router
from app.auth.temporary_accounts_repository import TemporaryCredentialCreate
from app.config import get_tts_config
from app.routes import admin, avatar, backgrounds, capabilities, mascots

_PATH = "/api/v1/me/capabilities"
_DEFAULTS = ("project-a", "character-a", "indextts", "voice-a")
_GRANTS = [
    (ResourceType.PROJECT, "project-a"),
    (ResourceType.AVATAR_CHARACTER, "character-a"),
    (ResourceType.AVATAR_MASCOT, "mascot-a"),
    (ResourceType.AVATAR_BACKGROUND, "background-a"),
    (ResourceType.CUSTOM_VOICE, "voice-a"),
    (ResourceType.CUSTOM_VOICE, "voice-b"),
    (ResourceType.ASR_ENGINE, "breeze"),
    (ResourceType.ASR_ENGINE, "r2t2"),
    (ResourceType.ASR_ENGINE, "r2t2-live"),
    (ResourceType.ASR_ENGINE, "browser"),
]


@pytest.fixture
def env(monkeypatch):
    for name, value in {
        "ASR_PROVIDER": "breeze",
        "ASR_BREEZE_URL": "https://private-breeze.example",
        "ASR_R2T2_URL": "",
        "ASR_R2T2_STREAM_URL": "wss://private-r2t2.example",
        "ASR_R2T2_SECRET_KEY": "private-asr-secret",
        "ASR_R2T2_DEV_URL": "",
        "ASR_SENSEVOICE_URL": "https://private-sensevoice.example",
    }.items():
        monkeypatch.setenv(name, value)
    get_tts_config.cache_clear()
    runtime = get_auth_runtime()
    root = runtime.users.create_root(username="ai360", password_hash="unused")
    metadata = {
        "voice-a": {"provider": "indextts"},
        "voice-b": {"provider": "cosyvoice"},
        "voice-other": {"provider": "cosyvoice"},
    }
    for resource_type, resource_id in [
        *_GRANTS,
        (ResourceType.PROJECT, "project-other"),
        (ResourceType.AVATAR_CHARACTER, "character-other"),
        (ResourceType.AVATAR_MASCOT, "mascot-other"),
        (ResourceType.AVATAR_BACKGROUND, "background-other"),
        (ResourceType.CUSTOM_VOICE, "voice-other"),
        (ResourceType.ASR_ENGINE, "sensevoice"),
        (ResourceType.ASR_ENGINE, "gemini-live"),
    ]:
        runtime.resources.upsert_system_resource(
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata.get(resource_id, {}),
        )
    user = runtime.users.create(
        username="caller",
        password_hash="unused",
        role=AccountRole.USER,
        created_by=root.id,
        grants=_GRANTS,
        defaults=_DEFAULTS,
    )
    runtime.account_access.set_asr_provider(user.id, "r2t2-live")
    characters = [
        {"char_id": "character-a", "label": "角色 A"},
        {"char_id": "character-other", "label": "其他角色"},
    ]
    monkeypatch.setattr(
        avatar, "get_store",
        lambda: SimpleNamespace(list_characters=lambda: characters),
    )
    monkeypatch.setattr(
        mascots, "get_character_store", avatar.get_store,
    )
    monkeypatch.setattr(
        mascots, "get_store", lambda: SimpleNamespace(list_mascots=lambda: [
            {"mascot_id": "mascot-a", "engine": "vrm"},
            {"mascot_id": "mascot-other", "engine": "vrm"},
        ]),
    )
    monkeypatch.setattr(
        backgrounds, "get_store",
        lambda: SimpleNamespace(list_backgrounds=lambda: [
            {"background_id": "background-a"},
            {"background_id": "background-other"},
        ]),
    )
    project_payload = {"projects": [
        {"project_id": "project-a", "label": "專案 A"},
        {"project_id": "project-other", "label": "其他專案"},
    ]}
    proxy = AsyncMock(return_value=JSONResponse(project_payload))
    monkeypatch.setattr(project_routes, "proxy_to_brain", proxy)
    monkeypatch.setattr(
        admin, "build_tts_provider_catalog",
        AsyncMock(return_value=[{
            "id": "indextts", "name": "IndexTTS",
            "default_voice": "voice-a", "voices": ["voice-a"],
        }, {
            "id": "cosyvoice", "name": "CosyVoice",
            "default_voice": "voice-b", "voices": ["voice-b", "voice-other"],
        }]),
    )
    app = FastAPI()
    for router in (
        capabilities.router, project_routes.router, avatar.router,
        mascots.router, backgrounds.router, admin.router, settings_router,
    ):
        app.include_router(router)
    app.add_middleware(FailClosedAuthMiddleware, runtime=runtime)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(
            runtime=runtime, root=root, user=user, client=client, proxy=proxy,
        )


def _headers(env, user=None):
    token = env.runtime.tokens.issue(user or env.user)
    return {
        "Authorization": f"Bearer {token}",
    }


def _assert_scoped(payload):
    assert payload["schema_version"] == 1
    assert set(payload) == {
        "schema_version", "account", "defaults", "projects", "characters",
        "mascots", "backgrounds", "tts", "asr",
    }
    assert [p["project_id"] for p in payload["projects"]] == ["project-a"]
    assert [p["char_id"] for p in payload["characters"]] == ["character-a"]
    assert [p["mascot_id"] for p in payload["mascots"]] == ["mascot-a"]
    assert [p["background_id"] for p in payload["backgrounds"]] == [
        "background-a",
    ]
    voices = {
        provider["id"]: provider["voices"]
        for provider in payload["tts"]["providers"]
    }
    assert voices == {"indextts": ["voice-a"], "cosyvoice": ["voice-b"]}
    assert payload["defaults"] == {
        "project_id": "project-a", "character_id": "character-a",
        "voice_provider": "indextts", "voice_id": "voice-a",
        "mascot_id": "", "background_id": "",
    }


@pytest.mark.parametrize("transport", ["session", "api_key", "cookie"])
def test_capabilities_share_live_scoped_lists_and_asr_settings(env, transport):
    headers = _headers(env)
    if transport == "api_key":
        _, secret = env.runtime.api_keys.create(
            actor_id=env.user.id, user_id=env.user.id, label="integration",
        )
        headers = {"Authorization": f"Bearer {secret}"}
    elif transport == "cookie":
        env.client.cookies.set(
            "openvman_session", env.runtime.tokens.issue(env.user),
        )
        headers = {}
    response = env.client.get(_PATH, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    _assert_scoped(payload)
    assert payload["account"] == {
        "id": env.user.id, "username": "caller", "role": "user",
    }
    for path, field in (
        ("/api/v1/projects", "projects"),
        ("/api/v1/avatar", "characters"),
        ("/api/v1/avatar/mascots", "mascots"),
        ("/api/v1/backgrounds", "backgrounds"),
    ):
        assert payload[field] == env.client.get(
            path, headers=headers,
        ).json()[field]
    assert payload["tts"]["providers"] == env.client.get(
        "/api/v1/tts/providers", headers=headers,
    ).json()
    asr_profile = env.client.get(
        "/api/v1/settings/my-asr-provider", headers=headers,
    ).json()
    assert {key: payload["asr"][key] for key in asr_profile} == asr_profile
    assert payload["asr"]["batch"] == [
        {"id": "breeze", "configured": True},
        {"id": "r2t2", "configured": False},
    ]
    assert payload["asr"]["stream"] == [
        {"id": "r2t2-live", "configured": True},
    ]
    assert payload["asr"]["browser"] == [
        {"id": "browser", "configured": None},
    ]
    assert "private-" not in response.text


def test_temporary_account_uses_the_same_grants(env):
    batch = env.runtime.temporary_accounts.create_batch(
        created_by=env.root.id,
        credentials=[
            TemporaryCredentialCreate(
                locator=f"temporary-{i}", password_hash="x",
            )
            for i in range(5)
        ],
        grants=_GRANTS, defaults=_DEFAULTS, duration_seconds=600,
    )
    temporary, _ = env.runtime.temporary_accounts.activate(
        user_id=batch.accounts[0].user.id, now=datetime.now(timezone.utc),
    )
    response = env.client.get(_PATH, headers=_headers(env, temporary))
    assert response.status_code == 200, response.text
    _assert_scoped(response.json())


@pytest.mark.parametrize("role", [AccountRole.ROOT, AccountRole.ADMIN])
def test_root_and_unscoped_admin_share_existing_lists(env, role):
    user = env.root if role is AccountRole.ROOT else env.runtime.users.create(
        username="admin", password_hash="unused", role=role,
        created_by=env.root.id,
    )
    headers = _headers(env, user)
    response = env.client.get(_PATH, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["projects"]) == 2
    assert len(payload["characters"]) == 2
    assert payload["tts"]["providers"] == env.client.get(
        "/api/v1/tts/providers", headers=headers,
    ).json()
    assert "voice-other" in {
        voice for provider in payload["tts"]["providers"]
        for voice in provider["voices"]
    }


def test_scoped_admin_cannot_discover_resources_above_its_ceiling(env):
    user = env.runtime.users.create(
        username="scoped-admin", password_hash="unused",
        role=AccountRole.ADMIN, created_by=env.root.id,
    )
    env.runtime.admin_scopes.replace(
        admin_user_id=user.id, updated_by=env.root.id,
        scoped=True, resources=_GRANTS,
    )
    response = env.client.get(_PATH, headers=_headers(env, user))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [p["project_id"] for p in payload["projects"]] == ["project-a"]
    assert [p["char_id"] for p in payload["characters"]] == ["character-a"]
    assert [p["mascot_id"] for p in payload["mascots"]] == ["mascot-a"]
    assert [p["background_id"] for p in payload["backgrounds"]] == [
        "background-a",
    ]
    assert {
        provider["id"]: provider["voices"]
        for provider in payload["tts"]["providers"]
    } == {"indextts": ["voice-a"], "cosyvoice": ["voice-b"]}
    assert payload["tts"]["providers"] == env.client.get(
        "/api/v1/tts/providers", headers=_headers(env, user),
    ).json()


@pytest.mark.parametrize("transport", ["session", "api_key"])
def test_revoked_grants_disappear_without_reissuing_credential(env, transport):
    headers = _headers(env)
    if transport == "api_key":
        _, secret = env.runtime.api_keys.create(
            actor_id=env.user.id, user_id=env.user.id, label="integration",
        )
        headers = {"Authorization": f"Bearer {secret}"}
    assert env.client.get(_PATH, headers=headers).status_code == 200
    retained = [
        grant for grant in _GRANTS
        if grant[1] not in {"voice-b", "r2t2-live", "background-a", "mascot-a"}
    ]
    env.runtime.account_access.replace(
        user_id=env.user.id, granted_by=env.root.id,
        grants=retained, defaults=_DEFAULTS,
    )
    response = env.client.get(_PATH, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mascots"] == payload["backgrounds"] == []
    assert payload["asr"]["stream"] == []
    assert payload["asr"]["effective"] == "breeze"
    assert [p["id"] for p in payload["tts"]["providers"]] == ["indextts"]


def test_anonymous_cannot_read_capabilities(env):
    assert env.client.get(_PATH).status_code == 401
    env.proxy.assert_not_awaited()


def test_openapi_exposes_capabilities_and_failure_responses(env):
    operation = env.client.app.openapi()["paths"][_PATH]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AccountCapabilities",
    }
    assert {"403", "502", "503"} <= set(operation["responses"])


def test_embed_cannot_expand_into_owner_capabilities(env):
    key = env.runtime.embed_keys.create(
        label="Partner", project_id="project-a",
        allowed_origins=["https://partner.example"],
        default_character_id="character-a", created_by=env.root.id,
    )
    response = env.client.get(_PATH, headers={
        "X-Embed-Key": key.key_id, "Origin": "https://partner.example",
    })
    assert response.status_code == 403
    env.proxy.assert_not_awaited()


@pytest.mark.parametrize("upstream_status, expected", [(401, 502), (503, 503)])
def test_project_failure_is_explicit(env, upstream_status, expected):
    env.proxy.return_value = JSONResponse(
        {"detail": "private upstream failure"}, status_code=upstream_status,
    )
    response = env.client.get(_PATH, headers=_headers(env))
    assert response.status_code == expected
    assert "projects" not in response.json()
    assert "private" not in response.text


@pytest.mark.parametrize("body", [b"not-json", b'{"projects": {}}'])
def test_invalid_project_response_is_not_an_empty_success(env, body):
    env.proxy.return_value = Response(body, status_code=200)
    assert env.client.get(_PATH, headers=_headers(env)).status_code == 502


def test_project_transport_failure_is_service_unavailable(env):
    env.proxy.side_effect = httpx.ConnectError("private upstream URL")
    response = env.client.get(_PATH, headers=_headers(env))
    assert response.status_code == 503
    assert "private" not in response.text


def test_authorization_repository_failure_cannot_return_empty_success(env):
    with env.runtime.database.transaction(write=True) as connection:
        connection.execute("DROP TABLE resource_grants")
    assert env.client.get(_PATH, headers=_headers(env)).status_code == 500


def test_project_id_narrows_asr_and_tts_to_the_project_policy(env):
    env.runtime.project_policies.replace(
        project_id="project-a",
        allowed_asr_engines=["r2t2", "browser"],
        default_asr_engine="r2t2",
        taiwanese_asr_engine="r2t2",
        allowed_tts_voices=["voice-b"],
        default_tts_voice="voice-b",
        updated_by=env.root.id,
    )
    response = env.client.get(
        _PATH, params={"project_id": "project-a"}, headers=_headers(env),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["asr"]["allowed"] == ["browser", "r2t2"]
    # 偏好 r2t2-live 被專案擋掉，改用專案預設。
    assert payload["asr"]["value"] == "r2t2-live"
    assert payload["asr"]["effective"] == "r2t2"
    assert payload["asr"]["batch"] == [
        {"id": "r2t2", "configured": False, "in_project_scope": True}
    ]
    assert payload["asr"]["stream"] == []
    assert {
        provider["id"]: provider["voices"]
        for provider in payload["tts"]["providers"]
    } == {"cosyvoice": ["voice-b"]}
    assert payload["project_policy"] == {
        "project_id": "project-a",
        "allowed_asr_engines": ["r2t2", "browser"],
        "default_asr_engine": "r2t2",
        "taiwanese_asr_engine": "r2t2",
        "allowed_tts_voices": ["voice-b"],
        "default_tts_voice": "voice-b",
        "effective_tts_voice": "voice-b",
        "allowed_characters": [],
        "default_character_id": None,
        "allowed_backgrounds": [],
        "default_background_id": None,
        "allowed_mascots": [],
        "default_mascot_id": None,
    }
    # 不帶 project_id 時回應一個欄位都沒變。
    _assert_scoped(env.client.get(_PATH, headers=_headers(env)).json())


def test_project_id_without_policy_reports_unrestricted_lists(env):
    plain = env.client.get(_PATH, headers=_headers(env)).json()
    scoped = env.client.get(
        _PATH, params={"project_id": "project-a"}, headers=_headers(env),
    ).json()
    plain_asr_with_scope = {
        **plain["asr"],
        "batch": [{**item, "in_project_scope": True} for item in plain["asr"]["batch"]],
        "stream": [{**item, "in_project_scope": True} for item in plain["asr"]["stream"]],
        "browser": [{**item, "in_project_scope": True} for item in plain["asr"]["browser"]],
    }
    assert scoped["asr"] == plain_asr_with_scope
    plain_tts_with_scope = {
        "providers": [
            {
                **provider,
                "in_project_scope": True,
                "voice_items": [
                    {"id": v, "in_project_scope": True} for v in provider["voices"]
                ],
            }
            for provider in plain["tts"]["providers"]
        ]
    }
    assert scoped["tts"] == plain_tts_with_scope
    assert scoped["project_policy"]["allowed_asr_engines"] == []
    assert scoped["project_policy"]["effective_tts_voice"] == "voice-a"


def test_project_id_outside_grants_is_404(env):
    response = env.client.get(
        _PATH, params={"project_id": "project-other"}, headers=_headers(env),
    )
    assert response.status_code == 404

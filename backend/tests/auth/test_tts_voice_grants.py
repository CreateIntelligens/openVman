"""TTS selection follows grants across providers and retains isolation."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.auth.dependencies import AuthTransport, CurrentAccount
from app.auth.models import AccountRole, ResourceType
from app.auth.runtime import build_auth_runtime
from app.auth.temporary_accounts_repository import TemporaryCredentialCreate
from app.auth.voice_access import (
    embed_tts_providers,
    resolve_tts_voice,
    scoped_tts_providers,
)
from app.config import TTSRouterConfig
from app.providers.voice_catalog import PROVIDER_NAMES
from app.routes import admin


@pytest.fixture
def runtime(tmp_path):
    runtime = build_auth_runtime(TTSRouterConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        env="dev",
        session_jwt_secret="tts-grants-test-secret-at-least-32",
        auth_database_path=str(tmp_path / "accounts.db"),
    ))
    runtime.users.create_root(username="ai360", password_hash="unused")
    resources = [
        (ResourceType.PROJECT, "project", {}),
        (ResourceType.AVATAR_CHARACTER, "avatar", {}),
        (ResourceType.CUSTOM_VOICE, "index-a", {"provider": "indextts"}),
        (ResourceType.CUSTOM_VOICE, "index-z", {"provider": "indextts"}),
        (ResourceType.CUSTOM_VOICE, "cosy-a", {
            "provider": "cosyvoice", "runtime_key": "upstream-a",
        }),
        (ResourceType.CUSTOM_VOICE, "cosy-z", {"provider": "cosyvoice"}),
        (ResourceType.CUSTOM_VOICE, "foreign", {"provider": "cosyvoice"}),
        (ResourceType.CUSTOM_VOICE, "legacy", {}),
        (ResourceType.CUSTOM_VOICE, "invalid", {"provider": "auto"}),
    ]
    for resource_type, resource_id, metadata in resources:
        runtime.resources.upsert_system_resource(
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata,
        )
    return runtime


@pytest.fixture(params=["formal", "temporary"])
def current(runtime, request):
    root = runtime.users.get_by_username("ai360")
    access = {
        "grants": [
            (ResourceType.PROJECT, "project"),
            (ResourceType.AVATAR_CHARACTER, "avatar"),
            *((ResourceType.CUSTOM_VOICE, voice) for voice in (
                "index-a", "index-z", "cosy-a", "cosy-z", "legacy", "invalid",
            )),
        ],
        "defaults": ("project", "avatar", "indextts", "index-z"),
    }
    if request.param == "temporary":
        batch = runtime.temporary_accounts.create_batch(
            created_by=root.id,
            credentials=[
                TemporaryCredentialCreate(str(index), "unused")
                for index in range(5)
            ],
            duration_seconds=3600,
            **access,
        )
        user = batch.accounts[0].user
    else:
        user = runtime.users.create(
            username="ordinary", password_hash="unused",
            role=AccountRole.USER, created_by=root.id, **access,
        )
    return CurrentAccount(user=user, transport=AuthTransport.BEARER)


def _resolve(current, runtime, provider="", voice=""):
    return resolve_tts_voice(
        current, runtime, requested_provider=provider, requested_voice=voice,
    )


def _clear_defaults(runtime, current, *, delete):
    with runtime.database.transaction(write=True) as connection:
        if delete:
            connection.execute(
                "DELETE FROM account_defaults WHERE user_id = ?",
                (current.user.id,),
            )
        else:
            connection.execute(
                "UPDATE account_defaults "
                "SET voice_id = '', voice_provider = '' "
                "WHERE user_id = ?", (current.user.id,),
            )


@pytest.mark.parametrize("provider", ["", "auto", "cosyvoice", " cosyvoice "])
def test_cross_provider_granted_voice_uses_metadata(
    current, runtime, provider,
):
    before = runtime.account_access.get_defaults(current.user.id)
    voice = _resolve(current, runtime, provider, " cosy-a ")
    assert voice is not None
    assert (voice.provider, voice.resource_id) == ("cosyvoice", "cosy-a")
    assert voice.runtime_key == "upstream-a"
    assert voice.cache_scope == "system:cosy-a"
    assert runtime.account_access.get_defaults(current.user.id) == before


@pytest.mark.parametrize("provider, voice", [
    ("cosyvoice", "foreign"),
    ("", "missing"),
    ("indextts", "cosy-a"),
    ("cosyvoice", "index-a"),
    ("cosyvoice", ""),
    ("", "invalid"),
])
def test_unauthorized_or_mismatched_voice_is_hidden(
    current, runtime, provider, voice,
):
    with pytest.raises(HTTPException) as error:
        _resolve(current, runtime, provider, voice)
    assert error.value.status_code == 404
    assert error.value.detail == "Resource not found"


def test_omitted_voice_uses_account_default(current, runtime):
    voice = _resolve(current, runtime)
    assert voice is not None
    assert (voice.provider, voice.resource_id) == ("indextts", "index-z")


def test_provider_list_groups_grants_with_per_provider_defaults(
    current, runtime,
):
    providers = {
        row["id"]: row for row in scoped_tts_providers(current, runtime)
    }
    assert set(providers) == {"indextts", "cosyvoice"}
    assert providers["indextts"]["default_voice"] == "index-z"
    assert providers["cosyvoice"]["default_voice"] == "cosy-a"
    assert set(providers["indextts"]["voices"]) == {
        "index-a", "index-z", "legacy",
    }
    assert providers["cosyvoice"]["voices"] == ["cosy-a", "cosy-z"]
    for provider, row in providers.items():
        assert row["name"] == PROVIDER_NAMES[provider]


@pytest.mark.parametrize("delete", [False, True])
def test_explicit_grants_work_without_defaults(current, runtime, delete):
    _clear_defaults(runtime, current, delete=delete)
    voice = _resolve(current, runtime, voice="cosy-a")
    assert voice is not None and voice.provider == "cosyvoice"
    providers = {
        row["id"]: row for row in scoped_tts_providers(current, runtime)
    }
    assert set(providers) == {"indextts", "cosyvoice"}
    assert providers["indextts"]["default_voice"] == "index-a"
    assert "legacy" not in providers["indextts"]["voices"]
    for provider, voice_id in (("", ""), ("indextts", "legacy")):
        with pytest.raises(HTTPException) as error:
            _resolve(current, runtime, provider, voice_id)
        assert error.value.status_code == 404


@pytest.mark.parametrize("provider", ["", "auto", "indextts"])
def test_legacy_voice_uses_trusted_defaults_only(current, runtime, provider):
    voice = _resolve(current, runtime, provider, "legacy")
    assert voice is not None and voice.provider == "indextts"
    with pytest.raises(HTTPException) as error:
        _resolve(current, runtime, "cosyvoice", "legacy")
    assert error.value.status_code == 404


def test_revoked_grant_disappears_from_resolution_and_listing(
    current, runtime,
):
    with runtime.database.transaction(write=True) as connection:
        connection.execute(
            "DELETE FROM resource_grants WHERE grantee_user_id = ? "
            "AND resource_type = ? AND resource_id = ?",
            (current.user.id, ResourceType.CUSTOM_VOICE.value, "cosy-a"),
        )
    with pytest.raises(HTTPException) as error:
        _resolve(current, runtime, voice="cosy-a")
    assert error.value.status_code == 404
    voices = [
        voice for row in scoped_tts_providers(current, runtime)
        for voice in row["voices"]
    ]
    assert "cosy-a" not in voices


def test_embed_keeps_single_bound_voice_even_when_account_has_more(
    current, runtime,
):
    key = runtime.embed_keys.create(
        label="Embed", project_id="project",
        allowed_origins=["https://example.test"],
        default_tts_provider="indextts", default_tts_voice="index-z",
    )
    embed = CurrentAccount(
        user=current.user, transport=AuthTransport.EMBED_KEY, embed_key=key,
    )
    voice = _resolve(embed, runtime)
    assert voice is not None and voice.resource_id == "index-z"
    assert embed_tts_providers(embed)[0]["voices"] == ["index-z"]
    for provider, voice_id in (
        ("cosyvoice", "cosy-a"), ("indextts", "index-a"),
        ("cosyvoice", "index-z"),
    ):
        with pytest.raises(HTTPException) as error:
            _resolve(embed, runtime, provider, voice_id)
        assert error.value.status_code == 404


@pytest.mark.parametrize("role", [AccountRole.ROOT, AccountRole.ADMIN])
def test_admin_explicit_voice_still_works_without_defaults(runtime, role):
    user = runtime.users.get_by_username("ai360")
    if role is AccountRole.ADMIN:
        user = runtime.users.create(
            username="admin", password_hash="unused", role=role,
        )
    current = CurrentAccount(user=user, transport=AuthTransport.BEARER)
    assert _resolve(current, runtime) is None
    voice = _resolve(current, runtime, voice="foreign")
    assert voice is not None and voice.provider == "cosyvoice"


def test_scoped_admin_lists_and_resolves_only_voices_in_scope(
    runtime, monkeypatch,
):
    root = runtime.users.get_by_username("ai360")
    user = runtime.users.create(
        username="scoped-admin", password_hash="unused",
        role=AccountRole.ADMIN, created_by=root.id,
    )
    runtime.admin_scopes.replace(
        admin_user_id=user.id, updated_by=root.id, scoped=True,
        resources=[(ResourceType.CUSTOM_VOICE, "cosy-a")],
    )
    catalog = AsyncMock(side_effect=AssertionError("must respect scope"))
    monkeypatch.setattr(admin, "build_tts_provider_catalog", catalog)
    current = CurrentAccount(user=user, transport=AuthTransport.BEARER)
    response = asyncio.run(admin.get_tts_providers(current, runtime))
    assert json.loads(response.body) == [{
        "id": "cosyvoice", "name": PROVIDER_NAMES["cosyvoice"],
        "default_voice": "cosy-a", "voices": ["cosy-a"],
    }]
    catalog.assert_not_awaited()
    voice = _resolve(current, runtime, voice="cosy-a")
    assert voice is not None and voice.provider == "cosyvoice"
    with pytest.raises(HTTPException) as error:
        _resolve(current, runtime, voice="foreign")
    assert error.value.status_code == 404

"""Voice defaults stay usable or explicitly unavailable after grant changes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.dependencies import AuthTransport, CurrentAccount
from app.auth.models import AccountRole, ResourceType
from app.auth.passwords import hash_password
from app.auth.repositories import (
    InvalidResourceGrantError,
    TemporaryCredentialCreate,
)
from app.auth.routes import auth_router
from app.auth.runtime import AuthRuntime, build_auth_runtime, get_auth_runtime
from app.config import TTSRouterConfig
from app.routes.admin import resolve_tts_voice, router

_PASSWORD = "voice-default-test-password"
_BAD_METADATA = [
    "{}",
    "",
    "{invalid",
    "[]",
    '{"provider": " "}',
    '{"provider": 17}',
    '{"provider": false}',
    '{"provider": null}',
]


@pytest.fixture(scope="module")
def password_hash():
    return hash_password(_PASSWORD)


@pytest.fixture()
def runtime(tmp_path: Path) -> AuthRuntime:
    runtime = build_auth_runtime(TTSRouterConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        env="dev",
        session_jwt_secret="test-only-voice-defaults-secret-32",
        auth_database_path=str(tmp_path / "accounts.db"),
    ))
    root = runtime.users.create_root(username="ai360", password_hash="unused")
    runtime.users.create(
        username="admin",
        password_hash="unused",
        role=AccountRole.ADMIN,
        created_by=root.id,
    )
    voice_resources: tuple[tuple[ResourceType, str, dict[str, object]], ...] = (
        (ResourceType.PROJECT, "project", {}),
        (ResourceType.AVATAR_CHARACTER, "avatar", {}),
        (ResourceType.CUSTOM_VOICE, "voice-a", {"provider": "indextts"}),
        (ResourceType.CUSTOM_VOICE, "voice-b", {"provider": "indextts"}),
        (ResourceType.CUSTOM_VOICE, "voice-c", {"provider": "cosyvoice"}),
    )
    for resource_type, resource_id, metadata in voice_resources:
        runtime.resources.upsert_system_resource(
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata,
        )
    return runtime


@pytest.fixture()
def client(runtime):
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(router)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    return TestClient(app)


def _grants(*voices):
    return [
        (ResourceType.PROJECT, "project"),
        (ResourceType.AVATAR_CHARACTER, "avatar"),
        *((ResourceType.CUSTOM_VOICE, voice) for voice in voices),
    ]


def _metadata(runtime, raw):
    with runtime.database.transaction(write=True) as connection:
        connection.execute(
            "UPDATE resources SET metadata_json = ? "
            "WHERE resource_type = ? AND resource_id = ?",
            (raw, ResourceType.CUSTOM_VOICE.value, "voice-a"),
        )


@pytest.mark.parametrize("raw", [*_BAD_METADATA, '{"provider": "auto"}'])
@pytest.mark.parametrize("has_valid_replacement", [False, True])
def test_scope_repair_login_and_tts(
    runtime, client, password_hash, raw, has_valid_replacement,
):
    admin = runtime.users.get_by_username("admin")
    root = runtime.users.get_by_username("ai360")
    retained_voices = (
        ["voice-a", "voice-b"] if has_valid_replacement else ["voice-a"]
    )
    user = runtime.users.create(
        username="voice-user",
        password_hash=password_hash,
        role=AccountRole.USER,
        created_by=admin.id,
        grants=_grants(*retained_voices, "voice-c"),
        defaults=("project", "avatar", "cosyvoice", "voice-c"),
    )
    _metadata(runtime, raw)
    runtime.admin_scopes.replace(
        admin_user_id=admin.id,
        updated_by=root.id,
        scoped=True,
        resources=_grants(*retained_voices),
    )

    login = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": _PASSWORD},
    )
    assert login.status_code == 200
    defaults = login.json()["account"]["defaults"]
    expected = ("voice-b", "indextts") if has_valid_replacement else ("", "")
    assert (defaults["voice_id"], defaults["voice_provider"]) == expected
    providers = client.get(
        "/api/v1/tts/providers",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )
    assert providers.status_code == 200
    current = CurrentAccount(user=user, transport=AuthTransport.BEARER)
    if has_valid_replacement:
        assert providers.json()[0]["id"] == "indextts"
        authorized = resolve_tts_voice(
            current, runtime, requested_provider="", requested_voice="",
        )
        assert authorized is not None
        assert authorized.provider == "indextts"
        assert authorized.resource_id == "voice-b"
    else:
        assert providers.json() == []
        for provider, voice in (("", ""), ("cosyvoice", "voice-a")):
            with pytest.raises(HTTPException) as error:
                resolve_tts_voice(
                    current, runtime,
                    requested_provider=provider, requested_voice=voice,
                )
            assert error.value.status_code == 404
        # Registry refreshes must not silently undo the requirement to assign
        # defaults again after the previous selection was revoked.
        _metadata(runtime, '{"provider": "indextts"}')
        with pytest.raises(HTTPException) as error:
            resolve_tts_voice(
                current, runtime,
                requested_provider="", requested_voice="voice-a",
            )
        assert error.value.status_code == 404


@pytest.mark.parametrize("operation", ["create", "replace", "batch", "demote"])
@pytest.mark.parametrize("supplied_provider", ["cosyvoice", ""])
def test_every_defaults_write_derives_registered_provider(
    runtime, operation, supplied_provider,
):
    root = runtime.users.get_by_username("ai360")
    access = {
        "grants": iter(_grants("voice-a")),
        "defaults": ("project", "avatar", supplied_provider, "voice-a"),
    }
    if operation == "batch":
        batch = runtime.temporary_accounts.create_batch(
            created_by=root.id,
            credentials=[
                TemporaryCredentialCreate(str(index), "hash")
                for index in range(5)
            ],
            duration_seconds=3600,
            **access,
        )
        assert all(
            account.defaults.voice_provider == "indextts"
            for account in batch.accounts
        )
        return
    user = runtime.users.create(
        username="write-target",
        password_hash="hash",
        role=AccountRole.ADMIN if operation == "demote" else AccountRole.USER,
        created_by=root.id,
        **(access if operation == "create" else {}),
    )
    if operation == "replace":
        runtime.account_access.replace(
            user_id=user.id, granted_by=root.id, **access,
        )
    elif operation == "demote":
        runtime.users.change_role(
            actor_id=root.id, user_id=user.id, role=AccountRole.USER, **access,
        )
    defaults = runtime.account_access.get_defaults(user.id)
    assert (defaults.voice_id, defaults.voice_provider) == ("voice-a", "indextts")


@pytest.mark.parametrize("raw", _BAD_METADATA)
def test_legacy_write_uses_explicit_provider(runtime, raw):
    _metadata(runtime, raw)
    user = runtime.users.create(
        username="legacy",
        password_hash="hash",
        role=AccountRole.USER,
        grants=_grants("voice-a"),
        defaults=("project", "avatar", "indextts", "voice-a"),
    )
    defaults = runtime.account_access.get_defaults(user.id)
    assert defaults is not None
    assert defaults.voice_provider == "indextts"
    current = CurrentAccount(user=user, transport=AuthTransport.BEARER)
    authorized = resolve_tts_voice(
        current, runtime, requested_provider="", requested_voice="",
    )
    assert authorized is not None
    assert authorized.provider == "indextts"
    assert authorized.resource_id == "voice-a"


@pytest.mark.parametrize("provider", ["", "auto"])
def test_unknown_provider_write_rolls_back(runtime, provider):
    _metadata(runtime, "{}")
    with pytest.raises(InvalidResourceGrantError, match="provider"):
        runtime.users.create(
            username="invalid",
            password_hash="hash",
            role=AccountRole.USER,
            grants=_grants("voice-a"),
            defaults=("project", "avatar", provider, "voice-a"),
        )
    assert runtime.users.get_by_username("invalid") is None


def test_auto_metadata_cannot_be_written_as_a_concrete_provider(runtime):
    _metadata(runtime, '{"provider": "auto"}')
    with pytest.raises(InvalidResourceGrantError, match="provider"):
        runtime.users.create(
            username="invalid-auto",
            password_hash="hash",
            role=AccountRole.USER,
            grants=_grants("voice-a"),
            defaults=("project", "avatar", "indextts", "voice-a"),
        )
    assert runtime.users.get_by_username("invalid-auto") is None

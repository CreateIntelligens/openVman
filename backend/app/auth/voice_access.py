"""Which TTS voices an account, admin or embed key may use and see."""

from __future__ import annotations

import json
from dataclasses import dataclass

from fastapi import HTTPException

from app.providers.voice_catalog import PROVIDER_NAMES

from .dependencies import CurrentAccount
from .models import (
    AccountType,
    ResourceRecord,
    ResourceType,
    is_at_least_admin,
)
from .resources import (
    ResourceNotFoundError,
    list_accessible_resources,
    resolve_resource,
)
from .runtime import AuthRuntime

_RESOURCE_NOT_FOUND = "Resource not found"


@dataclass(frozen=True, slots=True)
class AuthorizedVoice:
    """A voice resolved to the provider-facing identity and cache scope."""

    provider: str
    resource_id: str
    runtime_key: str
    cache_scope: str


def _voice_metadata(record: ResourceRecord) -> dict[str, object]:
    try:
        payload = json.loads(record.metadata_json)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _metadata_string(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    return value.strip() if isinstance(value, str) else ""


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=_RESOURCE_NOT_FOUND)


def _resolve_embed_tts_voice(
    current: CurrentAccount,
    runtime: AuthRuntime,
    requested_provider: str,
    requested_voice: str,
) -> AuthorizedVoice | None:
    """Fall back to the key's default voice, and refuse anything else.

    Embed 金鑰沒有帳號層的授權資料，發音人只能是金鑰上設定的那一個；
    請求指定了別的 provider/voice 就當作查無資源。
    """
    key = current.embed_key
    assert key is not None
    provider = requested_provider or key.default_tts_provider
    voice_id = requested_voice or key.default_tts_voice
    if not voice_id or not provider:
        # 金鑰沒設預設音色時不擋，交由下游服務用自己的預設值合成。
        return None
    if key.default_tts_provider and provider != key.default_tts_provider:
        raise _not_found()
    if key.default_tts_voice and voice_id != key.default_tts_voice:
        raise _not_found()

    record = runtime.resources.get(ResourceType.CUSTOM_VOICE, voice_id)
    if record is None:
        raise _not_found()
    metadata = _voice_metadata(record)
    registered_provider = _metadata_string(metadata, "provider")
    if registered_provider and provider != registered_provider:
        raise _not_found()
    runtime_key = _metadata_string(metadata, "runtime_key") or record.resource_id
    cache_owner = record.owner_user_id or "system"
    return AuthorizedVoice(
        provider=registered_provider or provider,
        resource_id=record.resource_id,
        runtime_key=runtime_key,
        cache_scope=f"{cache_owner}:{record.resource_id}",
    )


def resolve_tts_voice(
    current: CurrentAccount,
    runtime: AuthRuntime,
    *,
    requested_provider: str,
    requested_voice: str,
) -> AuthorizedVoice | None:
    """Resolve a voice before cache or provider access.

    Administrators retain unrestricted provider access. Other accounts must use
    their configured provider and an explicitly granted voice.
    """
    provider = requested_provider.strip()
    voice_id = requested_voice.strip()
    defaults = None

    if current.embed_key is not None:
        return _resolve_embed_tts_voice(current, runtime, provider, voice_id)

    is_unrestricted_admin = (
        current.user.account_type is AccountType.FORMAL
        and is_at_least_admin(current.user.role)
    )
    if not is_unrestricted_admin:
        defaults = runtime.account_access.get_defaults(current.user.id)
        if (
            defaults is None
            or not defaults.voice_provider
            or not defaults.voice_id
        ):
            raise _not_found()
        provider = provider or defaults.voice_provider
        voice_id = voice_id or defaults.voice_id
        if provider != defaults.voice_provider:
            raise _not_found()
    elif not voice_id:
        return None

    if not voice_id:
        raise _not_found()

    try:
        record = resolve_resource(
            runtime.resources,
            current.user,
            ResourceType.CUSTOM_VOICE,
            voice_id,
        )
    except ResourceNotFoundError as exc:
        raise _not_found() from exc

    metadata = _voice_metadata(record)
    registered_provider = _metadata_string(metadata, "provider")
    if registered_provider:
        if provider and provider != "auto" and provider != registered_provider:
            raise _not_found()
        provider = registered_provider
    elif defaults is not None:
        # Account defaults are administrator-selected with the grants, so they
        # remain authoritative for migrated rows that predate provider metadata.
        provider = defaults.voice_provider

    if not provider or provider == "auto":
        raise _not_found()

    runtime_key = _metadata_string(metadata, "runtime_key") or record.resource_id
    cache_owner = record.owner_user_id or "system"
    return AuthorizedVoice(
        provider=provider,
        resource_id=record.resource_id,
        runtime_key=runtime_key,
        cache_scope=f"{cache_owner}:{record.resource_id}",
    )


def embed_tts_providers(current: CurrentAccount) -> list[dict[str, object]]:
    """An embed key may only see the single provider and voice it carries."""
    key = current.embed_key
    if key is None or not key.default_tts_provider:
        return []
    return [
        {
            "id": key.default_tts_provider,
            "name": PROVIDER_NAMES.get(
                key.default_tts_provider,
                key.default_tts_provider,
            ),
            "default_voice": key.default_tts_voice,
            "voices": [key.default_tts_voice] if key.default_tts_voice else [],
        }
    ]


def scoped_tts_providers(
    current: CurrentAccount,
    runtime: AuthRuntime,
) -> list[dict[str, object]]:
    """A non-admin account sees its default provider and its granted voices."""
    defaults = runtime.account_access.get_defaults(current.user.id)
    if defaults is None or not defaults.voice_provider or not defaults.voice_id:
        return []

    voices: list[str] = []
    for record in list_accessible_resources(
        runtime.resources,
        current.user,
        ResourceType.CUSTOM_VOICE,
    ):
        registered_provider = _metadata_string(
            _voice_metadata(record),
            "provider",
        )
        if (
            registered_provider
            and registered_provider != defaults.voice_provider
        ):
            continue
        voices.append(record.resource_id)

    if not voices:
        return []
    default_voice = (
        defaults.voice_id if defaults.voice_id in voices else voices[0]
    )
    return [
        {
            "id": defaults.voice_provider,
            "name": PROVIDER_NAMES.get(
                defaults.voice_provider,
                defaults.voice_provider,
            ),
            "default_voice": default_voice,
            "voices": voices,
        }
    ]

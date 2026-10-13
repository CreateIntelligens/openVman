"""Which TTS voices an account, admin or embed key may use and see."""

from __future__ import annotations

import json
from dataclasses import dataclass

from fastapi import HTTPException

from app.providers.voice_catalog import PROVIDER_NAMES

from .dependencies import CurrentAccount
from .models import (
    AccountType,
    ProjectPolicyRecord,
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
_VOICE_NOT_ALLOWED = "Voice not allowed for this project"
EDGE_TTS_PROVIDER = "edge-tts"


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


def _not_allowed() -> HTTPException:
    # 帳號本來就看得到這個聲音，只是專案不允許：回 403 讓前台知道要換，而不是
    # 跟「查無資源」混在一起。
    return HTTPException(status_code=403, detail=_VOICE_NOT_ALLOWED)


def _policy_for(
    runtime: AuthRuntime,
    project_id: str | None,
) -> ProjectPolicyRecord | None:
    return runtime.project_policies.get(project_id) if project_id else None


def _registered_provider(record: ResourceRecord) -> str:
    return _metadata_string(_voice_metadata(record), "provider")


def _runtime_key(record: ResourceRecord) -> str:
    return _metadata_string(_voice_metadata(record), "runtime_key") or record.resource_id


def _resolve_embed_tts_voice(
    current: CurrentAccount,
    runtime: AuthRuntime,
    requested_provider: str,
    requested_voice: str,
    policy: ProjectPolicyRecord | None,
) -> AuthorizedVoice | None:
    """Fall back to the key's default voice, and refuse anything else.

    Embed 金鑰沒有帳號層的授權資料，發音人只能是金鑰上設定的那一個；
    請求指定了別的 provider/voice 就當作查無資源。金鑰沒設聲音時改用綁定專案
    的預設聲音；專案有限制時聲音必須在專案清單內。
    """
    key = current.embed_key
    assert key is not None
    provider = requested_provider or key.default_tts_provider
    voice_id = requested_voice or key.default_tts_voice
    restricted = policy is not None and policy.restricts_tts
    from_policy = False
    if not voice_id and policy is not None:
        voice_id = policy.default_tts_voice or (
            policy.allowed_tts_voices[0] if restricted else ""
        )
        from_policy = bool(voice_id)
    if not voice_id or (not provider and not (restricted or from_policy)):
        # 金鑰沒設預設音色、專案也沒意見時不擋，交由下游服務用自己的預設值合成。
        return None
    if key.default_tts_provider and provider and provider != key.default_tts_provider:
        raise _not_found()
    if key.default_tts_voice and voice_id != key.default_tts_voice:
        raise _not_found()

    record = runtime.resources.get(ResourceType.CUSTOM_VOICE, voice_id)
    if record is None:
        raise _not_found()
    metadata = _voice_metadata(record)
    registered_provider = _metadata_string(metadata, "provider")
    if registered_provider and provider and provider != registered_provider:
        raise _not_found()
    if policy is not None and not policy.allows_voice(record.resource_id):
        raise _not_allowed()
    provider = registered_provider or provider
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


def _accessible_voice(
    current: CurrentAccount,
    runtime: AuthRuntime,
    voice_id: str,
) -> bool:
    try:
        resolve_resource(
            runtime.resources,
            current.user,
            ResourceType.CUSTOM_VOICE,
            voice_id,
            admin_scopes=runtime.admin_scopes,
        )
    except ResourceNotFoundError:
        return False
    return True


def _default_voice_id(
    current: CurrentAccount,
    runtime: AuthRuntime,
    policy: ProjectPolicyRecord | None,
    account_default: str,
) -> str:
    """Project default → account default → first allowed voice, within both limits."""
    candidates: list[str] = []
    if policy is not None and policy.default_tts_voice:
        candidates.append(policy.default_tts_voice)
    if account_default:
        candidates.append(account_default)
    if policy is not None and policy.restricts_tts:
        candidates.extend(policy.allowed_tts_voices)
    if policy is None and candidates:
        # 沒有專案限制時照舊：直接用帳號預設，後面的授權檢查決定能不能用。
        return candidates[0]
    for candidate in candidates:
        if (policy is None or policy.allows_voice(candidate)) and _accessible_voice(
            current, runtime, candidate,
        ):
            return candidate
    return ""


def resolve_tts_voice(
    current: CurrentAccount,
    runtime: AuthRuntime,
    *,
    requested_provider: str,
    requested_voice: str,
    project_id: str | None = None,
) -> AuthorizedVoice | None:
    """Resolve a voice before cache or provider access.

    Administrators retain unrestricted provider access. Other accounts may use
    any accessible voice, with its registered provider as the authority.
    ``project_id`` must already be authorized for the caller; its policy
    narrows the usable voices for everyone, administrators included.
    """
    provider = requested_provider.strip()
    voice_id = requested_voice.strip()
    defaults = None
    policy = _policy_for(runtime, project_id)

    if current.embed_key is not None:
        return _resolve_embed_tts_voice(current, runtime, provider, voice_id, policy)

    is_unrestricted_admin = (
        current.user.account_type is AccountType.FORMAL
        and is_at_least_admin(current.user.role)
    )
    if not is_unrestricted_admin:
        defaults = runtime.account_access.get_defaults(current.user.id)
    if not voice_id:
        voice_id = _default_voice_id(
            current, runtime, policy, defaults.voice_id if defaults else "",
        )
        if not voice_id and is_unrestricted_admin and not (
            policy is not None and policy.restricts_tts
        ):
            return None

    if not voice_id:
        raise _not_found()

    try:
        record = resolve_resource(
            runtime.resources,
            current.user,
            ResourceType.CUSTOM_VOICE,
            voice_id,
            admin_scopes=runtime.admin_scopes,
        )
    except ResourceNotFoundError as exc:
        raise _not_found() from exc
    if policy is not None and not policy.allows_voice(record.resource_id):
        raise _not_allowed()

    metadata = _voice_metadata(record)
    registered_provider = _metadata_string(metadata, "provider")
    if registered_provider:
        if provider and provider != "auto" and provider != registered_provider:
            raise _not_found()
        provider = registered_provider
    elif not is_unrestricted_admin:
        # Account defaults are administrator-selected with the grants, so they
        # remain authoritative for rows that predate provider metadata.
        trusted_provider = defaults.voice_provider if defaults else ""
        if provider and provider != "auto" and provider != trusted_provider:
            raise _not_found()
        provider = trusted_provider

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


def _grouped(
    voices: list[tuple[str, str]],
    default_voice: str,
) -> list[dict[str, object]]:
    voices_by_provider: dict[str, list[str]] = {}
    for provider, voice_id in voices:
        voices_by_provider.setdefault(provider, []).append(voice_id)
    return [
        {
            "id": provider,
            "name": PROVIDER_NAMES.get(provider, provider),
            "default_voice": default_voice if default_voice in ids else ids[0],
            "voices": ids,
        }
        for provider, ids in voices_by_provider.items()
    ]


def embed_tts_providers(
    current: CurrentAccount,
    runtime: AuthRuntime | None = None,
    policy: ProjectPolicyRecord | None = None,
) -> list[dict[str, object]]:
    """An embed key may only see the single provider and voice it carries.

    金鑰沒設聲音時，看得到的是綁定專案允許的聲音（專案有限制時）；金鑰的聲音
    被專案擋掉時什麼都看不到，免得前台列出一個一用就 403 的選項。
    """
    key = current.embed_key
    if key is None:
        return []
    if policy is not None and policy.restricts_tts:
        if key.default_tts_voice and not policy.allows_voice(key.default_tts_voice):
            return []
    elif not key.default_tts_provider:
        return []
    if not key.default_tts_provider:
        if policy is None or runtime is None:
            return []
        voices = [
            (_registered_provider(record), record.resource_id)
            for voice_id in policy.allowed_tts_voices
            if (record := runtime.resources.get(ResourceType.CUSTOM_VOICE, voice_id))
            and _registered_provider(record) not in ("", "auto")
        ]
        return _grouped(voices, policy.default_tts_voice or "")
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
    policy: ProjectPolicyRecord | None = None,
) -> list[dict[str, object]]:
    """Group every accessible voice by its authoritative provider.

    帶專案時只列專案允許的聲音，預設聲音也改成專案預設（在清單內的話）。
    """
    defaults = runtime.account_access.get_defaults(current.user.id)
    fallback_provider = defaults.voice_provider if defaults else ""
    voices: list[tuple[str, str]] = []
    for record in list_accessible_resources(
        runtime.resources,
        current.user,
        ResourceType.CUSTOM_VOICE,
        admin_scopes=runtime.admin_scopes,
    ):
        if policy is not None and not policy.allows_voice(record.resource_id):
            continue
        provider = _registered_provider(record) or fallback_provider
        if not provider or provider == "auto":
            continue
        voices.append((provider, record.resource_id))

    preferred = (
        policy.default_tts_voice
        if policy is not None
        and policy.default_tts_voice
        and any(voice == policy.default_tts_voice for _, voice in voices)
        else (defaults.voice_id if defaults else "")
    )
    return _grouped(voices, preferred)


def tts_fallback_voice(
    runtime: AuthRuntime,
    policy: ProjectPolicyRecord | None,
) -> str | None:
    """The Edge voice a failed provider may fall back to.

    回傳 ""：照舊退回 Edge 的預設聲音（專案沒限制）。回傳 None：專案清單裡沒有
    Edge 的聲音，不准默默換成 Edge——寧可回錯誤，也不要讓專案沒開的引擎出聲。
    """
    if policy is None or not policy.restricts_tts:
        return ""
    for voice_id in policy.allowed_tts_voices:
        record = runtime.resources.get(ResourceType.CUSTOM_VOICE, voice_id)
        if record is not None and _registered_provider(record) == EDGE_TTS_PROVIDER:
            return _runtime_key(record)
    return None


def project_voice_for_providers(
    runtime: AuthRuntime,
    policy: ProjectPolicyRecord,
    providers: tuple[str, ...],
) -> tuple[str, str] | None:
    """First project-allowed voice served by one of ``providers``, in that order.

    台語分流換引擎時用：專案有限制就只能換到清單裡的聲音，找不到就不換。
    """
    records = [
        record
        for voice_id in policy.allowed_tts_voices
        if (record := runtime.resources.get(ResourceType.CUSTOM_VOICE, voice_id))
    ]
    for provider in providers:
        for record in records:
            if _registered_provider(record) == provider:
                return provider, _runtime_key(record)
    return None

"""Which TTS voices an account, admin or embed key may use and see."""

from __future__ import annotations

import json
from dataclasses import dataclass

from fastapi import HTTPException

from app.config import get_tts_config
from app.providers.cosyvoice_adapter import COSYVOICE_DEFAULT_VOICE, COSYVOICE_PROVIDER_NAME
from app.providers.indextts_adapter import (
    INDEXTTS_NURSE_PROVIDER_NAME,
    indextts_nurse_default_character,
    indextts_nurse_voice_id,
)
from app.providers.voice_catalog import PROVIDER_NAMES, voice_display_label
from app.providers.voxcpm_adapter import VOXCPM_DEFAULT_VOICE, VOXCPM_PROVIDER_NAME

from .dependencies import CurrentAccount
from .models import (
    AccountRole,
    AccountType,
    ProjectPolicyRecord,
    ResourceRecord,
    ResourceType,
    ResourceVisibility,
    is_at_least_admin,
)
from .project_resources import (
    effective_project_default,
    effective_project_resources,
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


def _voice_label(record: ResourceRecord) -> str:
    return voice_display_label(
        record.resource_id,
        _metadata_string(_voice_metadata(record), "label"),
    )


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
        if not voice_id and policy.project_id:
            voice_id = effective_project_default(
                runtime, None, policy.project_id, ResourceType.CUSTOM_VOICE
            ) or ""
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
    is_proj_or_assigned = False
    p_id = policy.project_id if policy else key.project_id
    if p_id:
        if runtime.project_resource_assignments.is_assigned(
            p_id, ResourceType.CUSTOM_VOICE, record.resource_id
        ) or (
            record.visibility is ResourceVisibility.PROJECT
            and record.owner_project_id == p_id
        ):
            is_proj_or_assigned = True
    if not is_proj_or_assigned and policy is not None and not policy.allows_voice(record.resource_id):
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
    project_id: str | None = None,
) -> str:
    """Project default → account default → first allowed voice, within both limits."""
    pid = project_id or (policy.project_id if policy else None)
    has_project_or_assigned = False
    if pid:
        if (
            runtime.project_resource_assignments.list_for_project(
                pid, resource_type=ResourceType.CUSTOM_VOICE
            )
            or runtime.resources.list_by_owner_project(
                pid, resource_type=ResourceType.CUSTOM_VOICE
            )
        ):
            has_project_or_assigned = True

    if has_project_or_assigned and pid:
        resolved = effective_project_default(
            runtime, current.user, pid, ResourceType.CUSTOM_VOICE
        )
        if resolved:
            return resolved

    candidates: list[str] = []
    if policy is not None and policy.default_tts_voice:
        candidates.append(policy.default_tts_voice)
    if account_default:
        candidates.append(account_default)
    if policy is not None and policy.restricts_tts:
        candidates.extend(policy.allowed_tts_voices)
    if policy is None and not pid and candidates:
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
            current,
            runtime,
            policy,
            defaults.voice_id if defaults else "",
            project_id=project_id,
        )
        if not voice_id and is_unrestricted_admin and not (
            policy is not None and policy.restricts_tts
        ):
            return None

    if not voice_id:
        raise _not_found()

    record: ResourceRecord | None = None
    is_project_or_assigned = False
    if project_id:
        assigned = runtime.project_resource_assignments.is_assigned(
            project_id, ResourceType.CUSTOM_VOICE, voice_id
        )
        rec = runtime.resources.get(ResourceType.CUSTOM_VOICE, voice_id)
        is_project_res = (
            rec is not None
            and rec.visibility is ResourceVisibility.PROJECT
            and rec.owner_project_id == project_id
        )
        if assigned or is_project_res:
            is_project_or_assigned = True
            record = rec

    if not is_project_or_assigned:
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
        is_root = current.embed_key is None and current.user.role is AccountRole.ROOT
        if not is_root and policy is not None and not policy.allows_voice(record.resource_id):
            raise _not_allowed()

    assert record is not None

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


def deployment_default_voice(provider: str) -> str:
    """The voice ``provider`` speaks with when a request names none.

    清單裡沒有帳號／專案偏好的引擎，預設要顯示部署真的會念的那個聲音，
    不能拿清單第一個（字母排序常是 child-female-01）充數。
    """
    cfg = get_tts_config()
    if provider == COSYVOICE_PROVIDER_NAME:
        return cfg.tts_cosyvoice_default_voice or COSYVOICE_DEFAULT_VOICE
    if provider == VOXCPM_PROVIDER_NAME:
        return cfg.tts_voxcpm_default_voice or VOXCPM_DEFAULT_VOICE
    if provider == "indextts":
        return cfg.tts_indextts_default_character
    if provider == INDEXTTS_NURSE_PROVIDER_NAME:
        # 清單裡是加了前綴的資源 ID，要比對得上才選得到。
        return indextts_nurse_voice_id(indextts_nurse_default_character(cfg))
    if provider == EDGE_TTS_PROVIDER:
        return cfg.edge_tts_voice
    return ""


def _default_for(provider: str, preferred: str, ids: list[str]) -> str:
    if preferred in ids:
        return preferred
    deployment = deployment_default_voice(provider)
    if deployment in ids:
        return deployment
    return ids[0] if ids else ""


def _grouped(
    voices: list[tuple[str, str, str]],
    default_voice: str,
) -> list[dict[str, object]]:
    voices_by_provider: dict[str, list[tuple[str, str]]] = {}
    for provider, voice_id, label in voices:
        voices_by_provider.setdefault(provider, []).append((voice_id, label))
    return [
        {
            "id": provider,
            "name": PROVIDER_NAMES.get(provider, provider),
            "default_voice": _default_for(provider, default_voice, [v for v, _ in items]),
            "voices": [v for v, _ in items],
            "voice_items": [{"id": v, "label": label} for v, label in items],
        }
        for provider, items in voices_by_provider.items()
    ]


def _grouped_scoped(
    voices: list[tuple[str, str, bool, str]],
    default_voice: str,
) -> list[dict[str, object]]:
    voices_by_provider: dict[str, list[tuple[str, bool, str]]] = {}
    for provider, voice_id, in_scope, label in voices:
        voices_by_provider.setdefault(provider, []).append((voice_id, in_scope, label))
    return [
        {
            "id": provider,
            "name": PROVIDER_NAMES.get(provider, provider),
            "default_voice": _default_for(provider, default_voice, [v for v, _, _ in items]),
            "voices": [v for v, _, _ in items],
            "in_project_scope": any(in_scope for _, in_scope, _ in items),
            "voice_items": [
                {"id": v, "in_project_scope": in_scope, "label": label}
                for v, in_scope, label in items
            ],
        }
        for provider, items in voices_by_provider.items()
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
    is_p_or_a = False
    if runtime is not None and key.project_id and key.default_tts_voice:
        rec = runtime.resources.get(ResourceType.CUSTOM_VOICE, key.default_tts_voice)
        if runtime.project_resource_assignments.is_assigned(
            key.project_id, ResourceType.CUSTOM_VOICE, key.default_tts_voice
        ) or (
            rec is not None
            and rec.visibility is ResourceVisibility.PROJECT
            and rec.owner_project_id == key.project_id
        ):
            is_p_or_a = True

    if policy is not None and policy.restricts_tts and not is_p_or_a:
        if key.default_tts_voice and not policy.allows_voice(key.default_tts_voice):
            return []
    elif not key.default_tts_provider:
        return []
    if not key.default_tts_provider:
        if runtime is None:
            return []
        p_id = policy.project_id if policy else key.project_id
        if not p_id:
            return []
        entries = effective_project_resources(
            runtime, None, p_id, ResourceType.CUSTOM_VOICE
        )
        voices = [
            (_registered_provider(record), record.resource_id, _voice_label(record))
            for entry in entries
            if (record := runtime.resources.get(ResourceType.CUSTOM_VOICE, entry.resource_id))
            and _registered_provider(record) not in ("", "auto")
        ]
        preferred = effective_project_default(
            runtime, None, p_id, ResourceType.CUSTOM_VOICE
        ) or ""
        return _grouped(voices, preferred)
    return [
        {
            "id": key.default_tts_provider,
            "name": PROVIDER_NAMES.get(
                key.default_tts_provider,
                key.default_tts_provider,
            ),
            "default_voice": key.default_tts_voice,
            "voices": [key.default_tts_voice] if key.default_tts_voice else [],
            "voice_items": [
                {"id": key.default_tts_voice, "label": _embed_voice_label(runtime, key.default_tts_voice)}
            ] if key.default_tts_voice else [],
        }
    ]


def _embed_voice_label(runtime: AuthRuntime | None, voice_id: str) -> str:
    record = runtime.resources.get(ResourceType.CUSTOM_VOICE, voice_id) if runtime else None
    return _voice_label(record) if record else voice_display_label(voice_id)


def scoped_tts_providers(
    current: CurrentAccount,
    runtime: AuthRuntime,
    policy: ProjectPolicyRecord | None = None,
    project_id: str | None = None,
) -> list[dict[str, object]]:
    """Group every accessible voice by its authoritative provider.

    帶專案時只列專案允許的聲音，預設聲音也改成專案預設（在清單內的話）。
    """
    defaults = runtime.account_access.get_defaults(current.user.id)
    fallback_provider = defaults.voice_provider if defaults else ""
    pid = project_id or (policy.project_id if policy else None)
    if pid:
        entries = effective_project_resources(
            runtime, current.user, pid, ResourceType.CUSTOM_VOICE
        )
        voices: list[tuple[str, str, bool]] = []
        for entry in entries:
            record = runtime.resources.get(ResourceType.CUSTOM_VOICE, entry.resource_id)
            if record is None:
                continue
            provider = _registered_provider(record) or fallback_provider
            if not provider or provider == "auto":
                continue
            voices.append((
                provider, record.resource_id, entry.in_project_scope, _voice_label(record),
            ))

        preferred = (
            effective_project_default(
                runtime,
                current.user,
                pid,
                ResourceType.CUSTOM_VOICE,
                available_entries=entries,
            )
            or (defaults.voice_id if defaults else "")
        )
        return _grouped_scoped(voices, preferred)

    voices: list[tuple[str, str, str]] = []
    for record in list_accessible_resources(
        runtime.resources,
        current.user,
        ResourceType.CUSTOM_VOICE,
        admin_scopes=runtime.admin_scopes,
    ):
        if record.visibility is ResourceVisibility.PROJECT:
            continue
        provider = _registered_provider(record) or fallback_provider
        if not provider or provider == "auto":
            continue
        voices.append((provider, record.resource_id, _voice_label(record)))

    preferred = defaults.voice_id if defaults else ""
    return _grouped(voices, preferred)


def tts_fallback_voice(
    runtime: AuthRuntime,
    policy: ProjectPolicyRecord | None,
    is_root: bool = False,
) -> str | None:
    """The Edge voice a failed provider may fall back to.

    回傳 ""：照舊退回 Edge 的預設聲音（專案沒限制或 ROOT 豁免）。回傳 None：專案清單裡沒有
    Edge 的聲音，不准默默換成 Edge——寧可回錯誤，也不要讓專案沒開的引擎出聲。
    """
    if is_root:
        return ""
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
    is_root: bool = False,
) -> tuple[str, str] | None:
    """First project-allowed voice served by one of ``providers``, in that order.

    台語分流換引擎時用：專案有限制就只能換到清單裡的聲音，找不到就不換。ROOT 豁免不受限。
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
    if is_root and providers:
        return providers[0], ""
    return None

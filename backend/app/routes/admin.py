from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.auth.dependencies import CurrentAccount, get_current_account
from app.auth.models import (
    AccountType,
    ResourceRecord,
    ResourceType,
    is_at_least_admin,
)
from app.auth.resources import (
    ResourceNotFoundError,
    list_accessible_resources,
    resolve_resource,
)
from app.auth.runtime import AuthRuntime, get_auth_runtime
from app.config import get_tts_config
from app.gateway.redis_pool import redis_available
from app.gateway.temp_storage import get_temp_storage
from app.health_payloads import build_backend_health_payload
from app.http_client import SharedAsyncClient
from app.observability import build_prometheus_response, get_metrics_snapshot
from app.providers.gemini_tts_adapter import GEMINI_DEFAULT_VOICE, GEMINI_PROVIDER_NAME
from app.providers.voxcpm_adapter import VOXCPM_DEFAULT_VOICE, VOXCPM_PROVIDER_NAME

logger = logging.getLogger("backend")
router = APIRouter()
_health_http = SharedAsyncClient()
_TTS_PROVIDER_TIMEOUT_SECONDS = 5
_INTERNAL_TOKEN_HEADER = "X-Internal-Token"
_RESOURCE_NOT_FOUND = "Resource not found"
_PROVIDER_NAMES = {
    "aws": "AWS Polly",
    "aws-polly": "AWS Polly",
    "edge-tts": "Edge TTS",
    "gcp": "GCP TTS",
    "gcp-tts": "GCP TTS",
    GEMINI_PROVIDER_NAME: "Gemini TTS",
    "indextts": "IndexTTS",
    VOXCPM_PROVIDER_NAME: "VoxCPM",
}


@dataclass(frozen=True, slots=True)
class AuthorizedVoice:
    """A voice resolved to the provider-facing identity and cache scope."""

    provider: str
    resource_id: str
    runtime_key: str
    cache_scope: str


async def close_http() -> None:
    await _health_http.close()


async def _fetch_provider_voices(
    base_url: str,
    voices_path: str,
    provider_name: str,
    *,
    headers: dict[str, str] | None = None,
) -> list[str]:
    voices_url = f"{base_url.rstrip('/')}{voices_path}"
    try:
        if headers is None:
            response = await _health_http.get().get(
                voices_url,
                timeout=_TTS_PROVIDER_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
        else:
            response = await _health_http.get().get(
                voices_url,
                timeout=_TTS_PROVIDER_TIMEOUT_SECONDS,
                headers=headers,
                follow_redirects=True,
            )
        response.raise_for_status()
        return _extract_voice_names(response.json())
    except Exception as exc:
        logger.warning("failed to fetch %s voices from %s: %s", provider_name, voices_url, exc)
        return []


async def _fetch_indextts_voices(base_url: str, internal_token: str) -> list[str]:
    return await _fetch_provider_voices(
        base_url,
        "/audio/voices",
        "indextts",
        headers={_INTERNAL_TOKEN_HEADER: internal_token},
    )


async def _fetch_gemini_voices(base_url: str) -> list[str]:
    return await _fetch_provider_voices(base_url, "/api/voices", "gemini")


async def _fetch_voxcpm_voices(base_url: str) -> list[tuple[str, str]]:
    """回傳 VoxCPM360 的 ``(voice_id, label)`` 清單。

    castvoice 的 /voices 用 ``voice_id``＋中文 ``label``，與其他 provider 的
    ``name`` 欄位不同，故不走 _extract_voice_names；label 留下來給 admin 選單。
    """
    voices_url = f"{base_url.rstrip('/')}/api/v1/tts/voices"
    try:
        response = await _health_http.get().get(
            voices_url,
            timeout=_TTS_PROVIDER_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning("failed to fetch voxcpm voices from %s: %s", voices_url, exc)
        return []

    voice_entries = payload.get("voices") if isinstance(payload, dict) else None
    if not isinstance(voice_entries, list):
        return []

    voices: list[tuple[str, str]] = []
    for entry in voice_entries:
        if not isinstance(entry, dict):
            continue
        voice_id = entry.get("voice_id")
        if not isinstance(voice_id, str) or not voice_id:
            continue
        label = entry.get("label")
        display_label = label if isinstance(label, str) and label else voice_id
        voices.append((voice_id, display_label))
    return voices


# 與 frontend/app/src/types/avatarBackground.ts 的 AVATAR_BACKGROUND_IDS 對應，
# label 沿用前台選單（SettingsModal）的中文名稱。
_BUILTIN_AVATAR_BACKGROUNDS = (
    ("dark", "深色"),
    ("clinic", "診間"),
    ("studio", "棚拍"),
)

_EDGE_TTS_VOICE_LABELS = {
    "zh-TW-HsiaoChenNeural": "曉臻 (Edge-TTS)",
    "zh-TW-YunJheNeural": "雲哲 (Edge-TTS)",
    "zh-CN-XiaoyiNeural": "曉伊 (Edge-TTS)",
}


async def sync_tts_custom_voices(runtime: AuthRuntime) -> None:
    """Register voices from enabled providers into the resource ownership registry."""
    cfg = get_tts_config()

    if cfg.edge_tts_enabled:
        edge_voices = ["zh-TW-HsiaoChenNeural", "zh-TW-YunJheNeural", "zh-CN-XiaoyiNeural"]
        if cfg.edge_tts_voice and cfg.edge_tts_voice not in edge_voices:
            edge_voices.insert(0, cfg.edge_tts_voice)
        for voice_id in edge_voices:
            label = _EDGE_TTS_VOICE_LABELS.get(voice_id, f"{voice_id} (Edge-TTS)")
            try:
                runtime.resources.upsert_system_resource(
                    resource_type=ResourceType.CUSTOM_VOICE,
                    resource_id=voice_id,
                    metadata={"provider": "edge-tts", "label": label},
                )
            except Exception as exc:
                logger.warning("failed to register edge-tts voice %s: %s", voice_id, exc)

    if cfg.tts_indextts_url:
        try:
            fetched_voices = await _fetch_indextts_voices(
                cfg.tts_indextts_url,
                cfg.gateway_internal_token,
            )
            for voice_id in fetched_voices:
                runtime.resources.upsert_system_resource(
                    resource_type=ResourceType.CUSTOM_VOICE,
                    resource_id=voice_id,
                    metadata={"provider": "indextts", "label": voice_id},
                )
        except Exception as exc:
            logger.warning("failed to sync indextts voices: %s", exc)

    if cfg.tts_gemini_url:
        try:
            gemini_voices = await _fetch_gemini_voices(cfg.tts_gemini_url)
            for voice_id in gemini_voices:
                runtime.resources.upsert_system_resource(
                    resource_type=ResourceType.CUSTOM_VOICE,
                    resource_id=voice_id,
                    metadata={"provider": GEMINI_PROVIDER_NAME, "label": voice_id},
                )
        except Exception as exc:
            logger.warning("failed to sync gemini voices: %s", exc)

    if cfg.tts_voxcpm_url:
        try:
            for voice_id, label in await _fetch_voxcpm_voices(cfg.tts_voxcpm_url):
                runtime.resources.upsert_system_resource(
                    resource_type=ResourceType.CUSTOM_VOICE,
                    resource_id=voice_id,
                    metadata={"provider": VOXCPM_PROVIDER_NAME, "label": label},
                )
        except Exception as exc:
            logger.warning("failed to sync voxcpm voices: %s", exc)

    if cfg.tts_gcp_enabled and cfg.tts_gcp_voice_name:
        try:
            runtime.resources.upsert_system_resource(
                resource_type=ResourceType.CUSTOM_VOICE,
                resource_id=cfg.tts_gcp_voice_name,
                metadata={"provider": "gcp", "label": f"{cfg.tts_gcp_voice_name} (GCP)"},
            )
        except Exception as exc:
            logger.warning("failed to register gcp voice: %s", exc)

    if cfg.tts_aws_enabled and cfg.tts_aws_polly_voice_id:
        try:
            runtime.resources.upsert_system_resource(
                resource_type=ResourceType.CUSTOM_VOICE,
                resource_id=cfg.tts_aws_polly_voice_id,
                metadata={"provider": "aws", "label": f"{cfg.tts_aws_polly_voice_id} (AWS)"},
            )
        except Exception as exc:
            logger.warning("failed to register aws voice: %s", exc)

    try:
        from app.routes.mascots import get_store as get_mascot_store
        for mascot in get_mascot_store().list_mascots():
            mid = mascot.get("mascot_id")
            mlabel = mascot.get("label") or mid
            if mid:
                runtime.resources.upsert_system_resource(
                    resource_type=ResourceType.AVATAR_MASCOT,
                    resource_id=mid,
                    metadata={"label": mlabel},
                )
    except Exception as exc:
        logger.warning("failed to sync mascots: %s", exc)

    try:
        from app.routes.backgrounds import get_store as get_background_store
        for bg in get_background_store().list_backgrounds():
            bid = bg.get("background_id")
            blabel = bg.get("label") or bid
            if bid:
                runtime.resources.upsert_system_resource(
                    resource_type=ResourceType.AVATAR_BACKGROUND,
                    resource_id=bid,
                    metadata={"label": blabel},
                )
    except Exception as exc:
        logger.warning("failed to sync backgrounds: %s", exc)

    # 前端內建的純 CSS 背景（AvatarCanvas 直接渲染，沒有實體檔案），
    # 仍要註冊成資源，否則管理端的權限選單看不到、也就無法指定成預設。
    for bid, blabel in _BUILTIN_AVATAR_BACKGROUNDS:
        try:
            runtime.resources.upsert_system_resource(
                resource_type=ResourceType.AVATAR_BACKGROUND,
                resource_id=bid,
                metadata={"label": blabel, "builtin": True},
            )
        except Exception as exc:
            logger.warning("failed to register builtin background %s: %s", bid, exc)


def _extract_voice_names(payload: object) -> list[str]:
    if isinstance(payload, dict):
        voices = payload.get("voices")
        candidates = voices if isinstance(voices, list) else payload.keys()
    elif isinstance(payload, list):
        candidates = payload
    else:
        return []

    names: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            names.append(candidate)
        elif isinstance(candidate, dict):
            name = candidate.get("name")
            if isinstance(name, str) and name:
                names.append(name)
    return names


def _prepend_default_voice(voices: list[str], default_voice: str) -> list[str]:
    if not default_voice or default_voice in voices:
        return voices
    return [default_voice, *voices]


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
        if defaults is None:
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


def _embed_tts_providers(current: CurrentAccount) -> list[dict[str, object]]:
    """An embed key may only see the single provider and voice it carries."""
    key = current.embed_key
    if key is None or not key.default_tts_provider:
        return []
    return [
        {
            "id": key.default_tts_provider,
            "name": _PROVIDER_NAMES.get(
                key.default_tts_provider,
                key.default_tts_provider,
            ),
            "default_voice": key.default_tts_voice,
            "voices": [key.default_tts_voice] if key.default_tts_voice else [],
        }
    ]


def _scoped_tts_providers(
    current: CurrentAccount,
    runtime: AuthRuntime,
) -> list[dict[str, object]]:
    defaults = runtime.account_access.get_defaults(current.user.id)
    if defaults is None:
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
            "name": _PROVIDER_NAMES.get(
                defaults.voice_provider,
                defaults.voice_provider,
            ),
            "default_voice": default_voice,
            "voices": voices,
        }
    ]


@router.get("/healthz", tags=["System"], summary="服務健康檢查")
async def healthz() -> dict:
    storage = get_temp_storage()
    quota = storage.check_quota()
    return await build_backend_health_payload(
        service="tts-router",
        redis_available=await redis_available(),
        quota=quota,
        client=_health_http.get(),
    )


UsageEndpoint = Literal["summary", "events"]
_USAGE_QUERY_KEYS: dict[UsageEndpoint, frozenset[str]] = {
    "summary": frozenset({
        "group_by",
        "user_id",
        "principal_type",
        "principal_id",
        "project_id",
        "session_id",
        "kind",
        "since",
        "until",
    }),
    "events": frozenset({
        "limit",
        "user_id",
        "principal_type",
        "principal_id",
        "project_id",
        "session_id",
        "trace_id",
        "kind",
        "since",
        "until",
    }),
}


async def _forward_usage_query(
    request: Request,
    current: CurrentAccount,
    endpoint: UsageEndpoint,
) -> JSONResponse:
    """Proxy a usage query to Brain, scoping non-admin accounts to themselves.

    Brain 的 ledger 沒有帳號概念，只認 header 帶進去的 user_id，所以權限
    收在這裡：管理員可帶任意 filter，其餘帳號的 user_id 一律覆寫成自己。
    """
    params = {
        key: value
        for key, value in request.query_params.items()
        if key in _USAGE_QUERY_KEYS[endpoint] and value
    }
    is_admin = (
        current.user.account_type is AccountType.FORMAL
        and is_at_least_admin(current.user.role)
    )
    if not is_admin:
        params["user_id"] = current.user.id

    cfg = get_tts_config()
    url = f"{cfg.brain_url.rstrip('/')}/brain/usage/{endpoint}"
    try:
        response = await _health_http.get().get(
            url,
            params=params,
            headers={_INTERNAL_TOKEN_HEADER: cfg.gateway_internal_token},
            timeout=_TTS_PROVIDER_TIMEOUT_SECONDS,
        )
        content = response.json()
    except Exception as exc:
        logger.warning("usage query to brain failed: %s", exc)
        return JSONResponse(status_code=502, content={"error": "brain unavailable"})
    return JSONResponse(status_code=response.status_code, content=content)


@router.get("/api/v1/usage/summary", tags=["Usage"], summary="Token 用量彙總")
async def get_usage_summary(
    request: Request,
    current: CurrentAccount = Depends(get_current_account),
) -> JSONResponse:
    return await _forward_usage_query(request, current, "summary")


@router.get("/api/v1/usage/events", tags=["Usage"], summary="Token 用量事件明細")
async def get_usage_events(
    request: Request,
    current: CurrentAccount = Depends(get_current_account),
) -> JSONResponse:
    return await _forward_usage_query(request, current, "events")


@router.get("/metrics", tags=["System"], summary="服務監控指標")
async def metrics() -> dict:
    return get_metrics_snapshot()


@router.get("/metrics/prometheus", tags=["System"], summary="Prometheus 格式指標")
async def metrics_prometheus():
    return build_prometheus_response()


@router.get("/api/v1/tts/providers", tags=["TTS"], summary="取得 TTS Provider 清單")
async def get_tts_providers(
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> JSONResponse:
    if current.embed_key is not None:
        return JSONResponse(content=_embed_tts_providers(current))
    if not (
        current.user.account_type is AccountType.FORMAL
        and is_at_least_admin(current.user.role)
    ):
        return JSONResponse(content=_scoped_tts_providers(current, runtime))

    cfg = get_tts_config()
    providers: list[dict] = [
        {"id": "auto", "name": "自動", "default_voice": "", "voices": []},
    ]

    if cfg.tts_indextts_url:
        # 探測 IndexTTS 健康狀態：抓不到 voices（容器掛掉/不可達）就不顯示，
        # 避免選單列出一個會 502 的 provider。auto 仍由 backend fallback 處理。
        fetched_voices = await _fetch_indextts_voices(
            cfg.tts_indextts_url,
            cfg.gateway_internal_token,
        )
        if fetched_voices:
            providers.append({
                "id": "indextts",
                "name": "IndexTTS",
                "default_voice": cfg.tts_indextts_default_character,
                "voices": _prepend_default_voice(
                    fetched_voices,
                    cfg.tts_indextts_default_character,
                ),
            })

    if cfg.tts_voxcpm_url:
        # 同 IndexTTS：抓不到 voices 就不列，避免選單出現會 502 的 provider。
        voxcpm_voices = [
            voice_id
            for voice_id, _label in await _fetch_voxcpm_voices(cfg.tts_voxcpm_url)
        ]
        if voxcpm_voices:
            default_voice = cfg.tts_voxcpm_default_voice or VOXCPM_DEFAULT_VOICE
            providers.append({
                "id": VOXCPM_PROVIDER_NAME,
                "name": "VoxCPM",
                "default_voice": default_voice,
                "voices": _prepend_default_voice(voxcpm_voices, default_voice),
            })

    if cfg.tts_gcp_enabled:
        providers.append({
            "id": "gcp",
            "name": "GCP TTS",
            "default_voice": cfg.tts_gcp_voice_name,
            "voices": [cfg.tts_gcp_voice_name],
        })

    if cfg.tts_aws_enabled:
        providers.append({
            "id": "aws",
            "name": "AWS Polly",
            "default_voice": cfg.tts_aws_polly_voice_id,
            "voices": [cfg.tts_aws_polly_voice_id],
        })

    if cfg.tts_gemini_url:
        fetched_voices = await _fetch_gemini_voices(cfg.tts_gemini_url)
        if fetched_voices:
            providers.append({
                "id": GEMINI_PROVIDER_NAME,
                "name": "Gemini TTS",
                "default_voice": GEMINI_DEFAULT_VOICE,
                "voices": _prepend_default_voice(
                    fetched_voices,
                    GEMINI_DEFAULT_VOICE,
                ),
            })

    if cfg.edge_tts_enabled:
        voices = ["zh-TW-HsiaoChenNeural", "zh-TW-YunJheNeural", "zh-CN-XiaoyiNeural"]
        if cfg.edge_tts_voice not in voices:
            voices.insert(0, cfg.edge_tts_voice)
        providers.append({
            "id": "edge-tts",
            "name": "Edge TTS",
            "default_voice": cfg.edge_tts_voice,
            "voices": voices,
        })

    return JSONResponse(content=providers)

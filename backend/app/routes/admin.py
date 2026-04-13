from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import get_tts_config
from app.gateway.redis_pool import redis_available
from app.gateway.temp_storage import get_temp_storage
from app.health_payloads import build_backend_health_payload
from app.http_client import SharedAsyncClient
from app.observability import get_metrics_snapshot
from app.providers.vibevoice_adapter import VIBEVOICE_DEFAULT_SPEAKER, VIBEVOICE_SPEAKERS

logger = logging.getLogger("backend")
router = APIRouter()
_health_http = SharedAsyncClient()
_TTS_PROVIDER_TIMEOUT_SECONDS = 5


async def close_http() -> None:
    await _health_http.close()


async def _fetch_indextts_voices(base_url: str) -> list[str]:
    voices_url = f"{base_url.rstrip('/')}/audio/voices"
    try:
        response = await _health_http.get().get(voices_url, timeout=_TTS_PROVIDER_TIMEOUT_SECONDS)
        response.raise_for_status()
        return _extract_voice_names(response.json())
    except Exception as exc:
        logger.warning("failed to fetch indextts voices from %s: %s", voices_url, exc)
        return []


def _extract_voice_names(payload: object) -> list[str]:
    if isinstance(payload, dict):
        candidates = payload.keys()
    elif isinstance(payload, list):
        candidates = payload
    else:
        return []
    return [name for name in candidates if isinstance(name, str) and name]


def _prepend_default_voice(voices: list[str], default_voice: str) -> list[str]:
    if not default_voice or default_voice in voices:
        return voices
    return [default_voice, *voices]


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


@router.get("/metrics", tags=["System"], summary="服務監控指標")
async def metrics() -> dict:
    return get_metrics_snapshot()


@router.get("/v1/tts/providers", tags=["TTS"], summary="取得 TTS Provider 清單")
async def get_tts_providers() -> JSONResponse:
    cfg = get_tts_config()
    providers: list[dict] = [
        {"id": "auto", "name": "自動", "default_voice": "", "voices": []},
    ]

    if cfg.tts_indextts_url:
        voices = _prepend_default_voice(
            await _fetch_indextts_voices(cfg.tts_indextts_url),
            cfg.tts_indextts_default_character,
        )
        providers.append({
            "id": "indextts",
            "name": "IndexTTS",
            "default_voice": cfg.tts_indextts_default_character,
            "voices": voices,
        })

    if cfg.tts_vibevoice_url:
        providers.append({
            "id": "vibevoice",
            "name": "VibeVoice",
            "default_voice": VIBEVOICE_DEFAULT_SPEAKER,
            "voices": list(VIBEVOICE_SPEAKERS),
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

    if cfg.edge_tts_enabled:
        providers.append({
            "id": "edge-tts",
            "name": "Edge TTS",
            "default_voice": cfg.edge_tts_voice,
            "voices": [cfg.edge_tts_voice],
        })

    return JSONResponse(content=providers)


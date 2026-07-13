from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import get_tts_config
from app.gateway.redis_pool import redis_available
from app.gateway.temp_storage import get_temp_storage
from app.health_payloads import build_backend_health_payload
from app.http_client import SharedAsyncClient
from app.observability import build_prometheus_response, get_metrics_snapshot
from app.providers.gemini_tts_adapter import GEMINI_DEFAULT_VOICE, GEMINI_PROVIDER_NAME

logger = logging.getLogger("backend")
router = APIRouter()
_health_http = SharedAsyncClient()
_TTS_PROVIDER_TIMEOUT_SECONDS = 5


async def close_http() -> None:
    await _health_http.close()


async def _fetch_provider_voices(
    base_url: str,
    voices_path: str,
    provider_name: str,
) -> list[str]:
    voices_url = f"{base_url.rstrip('/')}{voices_path}"
    try:
        response = await _health_http.get().get(voices_url, timeout=_TTS_PROVIDER_TIMEOUT_SECONDS)
        response.raise_for_status()
        return _extract_voice_names(response.json())
    except Exception as exc:
        logger.warning("failed to fetch %s voices from %s: %s", provider_name, voices_url, exc)
        return []


async def _fetch_indextts_voices(base_url: str) -> list[str]:
    return await _fetch_provider_voices(base_url, "/audio/voices", "indextts")


async def _fetch_gemini_voices(base_url: str) -> list[str]:
    return await _fetch_provider_voices(base_url, "/api/voices", "gemini")


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


@router.get("/metrics/prometheus", tags=["System"], summary="Prometheus 格式指標")
async def metrics_prometheus():
    return build_prometheus_response()


@router.get("/v1/tts/providers", tags=["TTS"], summary="取得 TTS Provider 清單")
async def get_tts_providers() -> JSONResponse:
    cfg = get_tts_config()
    providers: list[dict] = [
        {"id": "auto", "name": "自動", "default_voice": "", "voices": []},
    ]

    if cfg.tts_indextts_url:
        # 探測 IndexTTS 健康狀態：抓不到 voices（容器掛掉/不可達）就不顯示，
        # 避免選單列出一個會 502 的 provider。auto 仍由 backend fallback 處理。
        fetched_voices = await _fetch_indextts_voices(cfg.tts_indextts_url)
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

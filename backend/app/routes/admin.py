from __future__ import annotations

from dataclasses import asdict
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import get_tts_config
from app.gateway.embed_keys import EmbedKeyRecord, get_embed_key_store
from app.gateway.redis_pool import redis_available
from app.gateway.temp_storage import get_temp_storage
from app.health_payloads import build_backend_health_payload
from app.http_client import SharedAsyncClient
from app.observability import build_prometheus_response, get_metrics_snapshot
from app.providers.vibevoice_adapter import VIBEVOICE_DEFAULT_SPEAKER, VIBEVOICE_SPEAKERS

logger = logging.getLogger("backend")
router = APIRouter()
_health_http = SharedAsyncClient()
_TTS_PROVIDER_TIMEOUT_SECONDS = 5
_embed_key_store = get_embed_key_store()


class EmbedKeyCreateRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    allowed_domains: list[str] = Field(default_factory=list)
    note: str = ""


class EmbedKeyUpdateRequest(BaseModel):
    allowed_domains: list[str] | None = None
    note: str | None = None


def _record_payload(record: EmbedKeyRecord) -> dict:
    return asdict(record)


async def close_http() -> None:
    await _health_http.close()


@router.get("/api/admin/embed-keys", tags=["Admin"], summary="List embed API keys")
async def list_embed_keys() -> dict:
    return {"keys": [_record_payload(record) for record in _embed_key_store.list()]}


@router.post("/api/admin/embed-keys", tags=["Admin"], summary="Create embed API key")
async def create_embed_key(body: EmbedKeyCreateRequest) -> dict:
    created = _embed_key_store.create(
        tenant_id=body.tenant_id,
        allowed_domains=body.allowed_domains,
        note=body.note,
    )
    return {
        "record": _record_payload(created.record),
        "secret": created.secret,
    }


@router.patch("/api/admin/embed-keys/{key_id}", tags=["Admin"], summary="Update embed API key")
async def update_embed_key(key_id: str, body: EmbedKeyUpdateRequest) -> dict:
    updated = _embed_key_store.update(
        key_id,
        allowed_domains=body.allowed_domains,
        note=body.note,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="embed key not found")
    return _record_payload(updated)


@router.post("/api/admin/embed-keys/{key_id}/disable", tags=["Admin"], summary="Disable embed API key")
async def disable_embed_key(key_id: str) -> dict:
    record = _embed_key_store.disable(key_id)
    if record is None:
        raise HTTPException(status_code=404, detail="embed key not found")
    return _record_payload(record)


@router.post("/api/admin/embed-keys/{key_id}/enable", tags=["Admin"], summary="Re-enable embed API key")
async def enable_embed_key(key_id: str) -> dict:
    record = _embed_key_store.enable(key_id)
    if record is None:
        raise HTTPException(status_code=404, detail="embed key not found")
    return _record_payload(record)


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

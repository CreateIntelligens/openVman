"""openVman Backend — FastAPI entry point.

Serves TTS synthesis, MarkItDown document conversion, and gateway upload/queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, File, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from markitdown import MarkItDown
from pydantic import BaseModel, Field

from app.brain_proxy import _http as _brain_proxy_http
from app.brain_proxy import router as brain_proxy_router
from app.config import get_tts_config
from app.http_client import SharedAsyncClient
from app.gateway.crawl_adapter import _http as _crawl_http
from app.gateway.forward import _http as _forward_http
from app.internal_routes import _http as _internal_http
from app.internal_routes import router as internal_router
from app.error_payloads import upload_failed_response
from app.tts_text_cleaner import clean_for_tts
from app.utils.upload import UploadTooLargeError, cleanup_temp_path, persist_upload_to_tempfile
from app.gateway.redis_pool import close_redis, get_redis, redis_available
from app.gateway.routes import router as gateway_router
from app.gateway.temp_storage import get_temp_storage, reset_temp_storage
from app.gateway.brain_live_relay import BrainLiveRelay, DEFAULT_VOICE_SOURCE, _normalize_voice_source
from app.gateway.worker import (
    get_api_tool_plugin,
    get_camera_plugin,
    get_web_crawler_plugin,
    reset_plugins,
)
from app.health_payloads import build_backend_health_payload
from app.observability import (
    get_metrics_snapshot,
    record_interruption,
    set_active_sessions,
)
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.tts_cache import CachedTTSEntry, cache_get, cache_put, make_cache_key
from app.providers.vibevoice_adapter import VIBEVOICE_DEFAULT_SPEAKER, VIBEVOICE_SPEAKERS
from app.service import TTSRouterService
from app.session_manager import SessionManager
from app.guard_agent import GuardAgent

logger = logging.getLogger("backend")
_service: TTSRouterService | None = None
_md_converter: MarkItDown | None = None
_session_manager: SessionManager = SessionManager()
_guard_agent: GuardAgent = GuardAgent()
_health_http = SharedAsyncClient()
_BRAIN_OPENAPI_TIMEOUT_SECONDS = 5
_TTS_PROVIDER_TIMEOUT_SECONDS = 5


def _get_service() -> TTSRouterService:
    global _service
    if _service is None:
        _service = TTSRouterService(get_tts_config())
    return _service


def _get_md_converter() -> MarkItDown:
    global _md_converter
    if _md_converter is None:
        _md_converter = MarkItDown()
    return _md_converter


def _get_requested_voice_source(data: dict[str, Any]) -> str:
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, dict):
        return DEFAULT_VOICE_SOURCE
    return _normalize_voice_source(str(capabilities.get("voice_source", "")))


async def _startup_gateway_resources() -> None:
    storage = get_temp_storage()
    await storage.start_cleanup_loop()
    await get_redis()
    get_camera_plugin()
    get_api_tool_plugin()
    get_web_crawler_plugin()


async def _shutdown_gateway_resources() -> None:
    storage = get_temp_storage()
    await storage.stop_cleanup_loop()
    from app.gateway.queue import close_arq_pool

    await close_arq_pool()
    await close_redis()
    reset_temp_storage()
    reset_plugins()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await _startup_gateway_resources()
    await _build_openapi_schema()
    logger.info("backend startup complete")
    try:
        yield
    finally:
        await _brain_proxy_http.close()
        await _internal_http.close()
        await _forward_http.close()
        await _crawl_http.close()
        await _health_http.close()
        await _shutdown_gateway_resources()
        logger.info("backend shutdown complete")


app = FastAPI(title="openVman Backend", lifespan=lifespan)

# --- Gateway router ---
app.include_router(gateway_router)

# --- Internal routes (enrich from gateway) ---
app.include_router(internal_router)

# --- Public API facade (/api/* → internal brain service) ---
app.include_router(brain_proxy_router)


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    session = _session_manager.create_session(client_id, websocket=websocket)
    set_active_sessions(len(_session_manager.active_sessions))
    logger.info(f"WebSocket session created: {session.session_id} for client: {client_id}")

    heartbeat_task = asyncio.create_task(_run_heartbeat(websocket, session.session_id))
    session.add_task(heartbeat_task)

    try:
        while True:
            data_str = await websocket.receive_text()
            data = json.loads(data_str)
            event = data.get("event")
            if event == "pong":
                continue

            await _handle_websocket_event(event, data, session, websocket)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session.session_id}")
    except Exception as e:
        logger.error(f"WebSocket error in {session.session_id}: {e}")
    finally:
        await session.interrupt_tasks()
        if session.brain_live_relay is not None:
            await session.brain_live_relay.close()
        _session_manager.remove_session(session.session_id)
        set_active_sessions(len(_session_manager.active_sessions))


async def _run_heartbeat(websocket: WebSocket, session_id: str):
    """Periodically send pings to keep the connection alive."""
    try:
        while True:
            await asyncio.sleep(30)
            if websocket.client_state.name == "DISCONNECTED":
                break
            await websocket.send_json({"event": "ping", "timestamp": int(time.time() * 1000)})
    except Exception as e:
        logger.debug(f"Heartbeat stopped for {session_id}: {e}")


async def _handle_websocket_event(event: str | None, data: dict, session: Any, websocket: WebSocket):
    """Route WebSocket events to specific handlers."""
    if event == "client_init":
        await _handle_client_init(data, session, websocket)
    elif event == "client_interrupt":
        await _handle_client_interrupt(data, session, websocket)
    elif event == "set_lip_sync_mode":
        _handle_set_lip_sync_mode(data, session)
    elif event == "user_speak":
        await _handle_user_speak(data, session, websocket)
    elif event in ("client_audio_chunk", "client_audio_end"):
        await _handle_client_audio_event(data, session, websocket)
    elif event:
        logger.warning(f"Unhandled WebSocket event: {event}")


async def _handle_client_init(data: dict, session: Any, websocket: WebSocket):
    await websocket.send_json({
        "event": "server_init_ack",
        "session_id": session.session_id,
        "server_version": "1.0.0",
        "status": "ok",
        "timestamp": int(time.time() * 1000)
    })
    session.metadata["client_id"] = data.get("client_id", session.session_id)
    session.metadata["voice_source"] = _get_requested_voice_source(data)
    capabilities = data.get("capabilities") or {}
    chat_session_id = str(capabilities.get("session_id", "")).strip()
    if chat_session_id:
        session.metadata["chat_session_id"] = chat_session_id


async def _handle_client_interrupt(data: dict, session: Any, websocket: WebSocket):
    text = data.get("partial_asr") or ""
    action = await _guard_agent.classify(text)

    if action != "STOP":
        logger.debug(f"Ignoring potential interruption: {text}")
        return

    cancelled = await session.interrupt_tasks()
    record_interruption(reason="user")
    if cancelled > 0:
        logger.info(f"Interrupted {cancelled} tasks for session {session.session_id}")

    if session.brain_live_relay is not None:
        await session.brain_live_relay.send_event({
            "event": "client_interrupt",
            "partial_asr": text,
            "timestamp": int(time.time() * 1000),
        })

    await websocket.send_json({
        "event": "server_stop_audio",
        "session_id": session.session_id,
        "timestamp": int(time.time() * 1000),
        "reason": "user_interruption"
    })


def _handle_set_lip_sync_mode(data: dict, session: Any):
    mode = data.get("mode")
    if mode in ["dinet", "wav2lip", "webgl"]:
        session.lip_sync_mode = mode
        logger.info(f"Session {session.session_id} lip-sync mode set to {mode}")
    else:
        logger.warning(f"Invalid lip-sync mode: {mode}")


async def _handle_user_speak(data: dict, session: Any, websocket: WebSocket):
    text = data.get("text")
    if not text:
        logger.warning("user_speak received with no text")
        return

    await _ensure_brain_relay(session, websocket)
    await session.brain_live_relay.send_event({
        "event": "user_speak",
        "text": text,
        "timestamp": int(time.time() * 1000),
    })


async def _handle_client_audio_event(data: dict, session: Any, websocket: WebSocket):
    await _ensure_brain_relay(session, websocket)
    await session.brain_live_relay.send_event(data)


async def _ensure_brain_relay(session: Any, websocket: WebSocket):
    if session.brain_live_relay is None:
        session.brain_live_relay = BrainLiveRelay(
            session,
            voice_source=session.metadata.get("voice_source", DEFAULT_VOICE_SOURCE),
            event_sink=websocket.send_json,
        )


def _merge_tag_metadata(existing_tags: list[dict], extra_tags: list[dict]) -> list[dict]:
    merged_dict = {}
    for tag in existing_tags + extra_tags:
        name = str(tag.get("name", "")).strip()
        if name:
            merged_dict[name] = {**merged_dict.get(name, {}), **tag}
    return list(merged_dict.values())


def _merge_component_sections(existing_components: dict, extra_components: dict) -> dict:
    merged = dict(existing_components)
    for section_name, section_values in extra_components.items():
        merged[section_name] = {**merged.get(section_name, {}), **section_values}
    return merged


def _merge_brain_openapi(base_schema: dict, brain_schema: dict) -> dict:
    merged = dict(base_schema)
    merged_paths = dict(merged.get("paths", {}))
    for path, path_item in brain_schema.get("paths", {}).items():
        if path.startswith("/brain/"):
            merged_paths[path.replace("/brain/", "/api/", 1)] = path_item
    merged["paths"] = merged_paths
    merged["components"] = _merge_component_sections(
        merged.get("components", {}),
        brain_schema.get("components", {}),
    )
    merged["tags"] = _merge_tag_metadata(
        merged.get("tags", []),
        brain_schema.get("tags", []),
    )
    return merged


async def _fetch_brain_openapi() -> dict | None:
    brain_openapi_url = f"{get_tts_config().brain_url}/brain/openapi.json"
    try:
        resp = await _health_http.get().get(brain_openapi_url, timeout=_BRAIN_OPENAPI_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("failed to fetch brain openapi from %s: %s", brain_openapi_url, exc)
        return None


async def _fetch_indextts_voices(base_url: str) -> list[str]:
    voices_url = f"{base_url.rstrip('/')}/audio/voices"
    try:
        resp = await _health_http.get().get(voices_url, timeout=_TTS_PROVIDER_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return _extract_voice_names(resp.json())
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


def _cached_speech_response(entry: CachedTTSEntry) -> Response:
    return Response(
        content=entry.audio_bytes,
        media_type=entry.content_type,
        headers={
            "X-TTS-Latency-Ms": "0",
            "X-TTS-Provider": entry.provider,
            "X-TTS-Cache-Hit": "true",
        },
    )


def _to_cached_tts_entry(result: NormalizedTTSResult) -> CachedTTSEntry:
    from dataclasses import fields as dc_fields
    return CachedTTSEntry(**{f.name: getattr(result, f.name) for f in dc_fields(CachedTTSEntry)})


_openapi_built = False


async def _build_openapi_schema() -> dict:
    global _openapi_built
    if app.openapi_schema is not None:
        return app.openapi_schema

    local_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )

    if not _openapi_built:
        brain_schema = await _fetch_brain_openapi()
        _openapi_built = True
        if brain_schema is not None:
            app.openapi_schema = _merge_brain_openapi(local_schema, brain_schema)
            return app.openapi_schema

    app.openapi_schema = local_schema
    return app.openapi_schema


def custom_openapi() -> dict:
    if app.openapi_schema is not None:
        return app.openapi_schema

    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        local_schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
        )
        loop.create_task(_build_openapi_schema())
        return local_schema

    return asyncio.run(_build_openapi_schema())


app.openapi = custom_openapi


class SpeechRequest(BaseModel):
    """OpenAI-compatible TTS request body."""

    input: str
    voice: str = ""
    provider: str = ""
    response_format: str = "wav"
    speed: float = 1.0


# ---------------------------------------------------------------------------
# Health & metrics
# ---------------------------------------------------------------------------


@app.get(
    "/healthz",
    tags=["System"],
    summary="服務健康檢查",
    description="檢查 Backend 的服務狀態，包含 TTS、Redis 與磁碟空間容量。",
)
async def healthz() -> dict:
    storage = get_temp_storage()
    quota = storage.check_quota()
    return await build_backend_health_payload(
        service="tts-router",
        redis_available=await redis_available(),
        quota=quota,
        client=_health_http.get(),
    )


@app.get(
    "/metrics",
    tags=["System"],
    summary="服務監控指標",
    description="取得 Prometheus 格式的監控與效能指標列表。",
)
async def metrics() -> dict:
    return get_metrics_snapshot()


# ---------------------------------------------------------------------------
# TTS synthesis
# ---------------------------------------------------------------------------


@app.post(
    "/v1/audio/speech",
    tags=["TTS"],
    summary="文字轉語音",
    description="將文字轉換為音訊 (TTS)。相容於 OpenAI Speech API 格式。\n\n**所需欄位**：\n- `input` (Body, str): 要轉換的文字內容\n- `voice` (Body, str, 選填): 語音音色/說話者名稱\n- `response_format` (Body, str, 預設 'wav'): 輸出音訊格式\n- `speed` (Body, float, 預設 1.0): 語速設定",
)
async def create_speech(body: SpeechRequest) -> Response:
    cfg = get_tts_config()
    svc = _get_service()
    cleaned_text = clean_for_tts(body.input)
    request = SynthesizeRequest(
        text=cleaned_text,
        voice_hint=body.voice,
    )
    cache_key: str | None = None

    if cfg.tts_cache_enabled:
        cache_key = make_cache_key(cleaned_text, body.voice, body.provider)
        cached = await cache_get(cache_key)
        if cached is not None:
            return _cached_speech_response(cached)

    try:
        output = svc.synthesize(request, provider=body.provider)
    except RuntimeError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})

    headers = {
        "X-TTS-Latency-Ms": str(round(output.result.latency_ms, 2)),
        "X-TTS-Provider": output.result.provider,
        "X-TTS-Cache-Hit": "false",
    }
    if output.fallback:
        headers["X-TTS-Fallback"] = "true"
        headers["X-TTS-Fallback-Reason"] = output.fallback_reason

    if cache_key is not None:
        import asyncio
        asyncio.create_task(cache_put(
            cache_key,
            _to_cached_tts_entry(output.result),
            cfg.tts_cache_ttl_seconds,
        ))

    return Response(
        content=output.result.audio_bytes,
        media_type=output.result.content_type,
        headers=headers,
    )


@app.get(
    "/v1/tts/providers",
    tags=["TTS"],
    summary="取得 TTS Provider 清單",
    description="回傳所有已啟用的 TTS provider 及其可用 voice 清單。",
)
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


# ---------------------------------------------------------------------------
# MarkItDown — document-to-markdown conversion
# ---------------------------------------------------------------------------


@app.post(
    "/documents/convert",
    tags=["Documents"],
    summary="文件轉 Markdown",
    description="上傳文件（支援 Office 檔案等），將其轉換成 Markdown 格式回傳。\n\n**所需欄位**：\n- `file` (Form, UploadFile): 要轉換的檔案",
)
async def convert(file: UploadFile = File(...)) -> JSONResponse:
    suffix = os.path.splitext(file.filename or "")[1]
    tmp_path: str | None = None
    cfg = get_tts_config()
    try:
        tmp_path, total_bytes = await persist_upload_to_tempfile(
            file,
            suffix=suffix,
            max_bytes=cfg.markitdown_max_upload_bytes,
        )
        logger.info("Converting file: %s (%d bytes)", file.filename, total_bytes)
        result = _get_md_converter().convert(tmp_path)

        return JSONResponse(
            content={
                "markdown": result.text_content,
                "page_count": None,
            }
        )
    except UploadTooLargeError as exc:
        limit_mb = exc.limit_bytes / (1024 * 1024)
        return upload_failed_response(
            status_code=413,
            error=f"檔案超過大小限制（上限 {limit_mb:.0f} MB）",
        )
    except Exception as exc:
        logger.error("Conversion failed: %s", exc)
        return upload_failed_response(
            status_code=500,
            error=str(exc),
        )
    finally:
        await file.close()
        cleanup_temp_path(tmp_path)


def run_server() -> None:
    import uvicorn

    cfg = get_tts_config()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=cfg.backend_port,
        reload=cfg.is_dev,
    )


if __name__ == "__main__":
    run_server()

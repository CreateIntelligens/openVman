"""openVman Backend FastAPI entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic

import httpx
from fastapi import FastAPI, File, Request, Response, UploadFile
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from markitdown import MarkItDown
from pydantic import BaseModel, Field

from app.observability import (
    normalize_http_metrics_endpoint,
    record_http_request,
    should_record_http_metrics,
)
from app.brain_proxy import _http as _brain_proxy_http
from app.brain_proxy import router as brain_proxy_router
from app.config import get_tts_config
from app.http_client import SharedAsyncClient
from app.gateway import websocket as websocket_routes
from app.gateway.crawl_adapter import _http as _crawl_http
from app.gateway.forward import _http as _forward_http
from app.internal_routes import _http as _internal_http
from app.internal_routes import router as internal_router
from app.routes import admin as admin_routes
from app.error_payloads import upload_failed_response
from app.tts_text_cleaner import clean_for_tts
from app.utils.upload import UploadTooLargeError, cleanup_temp_path, persist_upload_to_tempfile
from app.gateway.redis_pool import close_redis, get_redis
from app.gateway.routes import router as gateway_router
from app.gateway.temp_storage import get_temp_storage, reset_temp_storage
from app.gateway.worker import (
    get_api_tool_plugin,
    get_camera_plugin,
    get_web_crawler_plugin,
    reset_plugins,
)
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.tts_cache import CachedTTSEntry, cache_get, cache_put, make_cache_key
from app.service import TTSRouterService

logger = logging.getLogger("backend")

_ACCESS_LOG_SILENT_PATHS = frozenset({"/api/health", "/healthz"})


class _SilentAccessPathsFilter(logging.Filter):
    """Drop uvicorn access log lines for infra polling endpoints."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn access log: args = (client, method, path, http_version, status)
        if not isinstance(args, tuple) or len(args) < 3:
            return True
        path = str(args[2]).split("?")[0]
        return path not in _ACCESS_LOG_SILENT_PATHS


logging.getLogger("uvicorn.access").addFilter(_SilentAccessPathsFilter())

_service: TTSRouterService | None = None
_md_converter: MarkItDown | None = None
_health_http = SharedAsyncClient()
_BRAIN_OPENAPI_TIMEOUT_SECONDS = 5


def _get_service() -> TTSRouterService:
    global _service
    _service = _service or TTSRouterService(get_tts_config())
    return _service


def _get_md_converter() -> MarkItDown:
    global _md_converter
    _md_converter = _md_converter or MarkItDown()
    return _md_converter


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
        clients = [_brain_proxy_http, _internal_http, _forward_http, _crawl_http, _health_http]
        await asyncio.gather(*(c.close() for c in clients), admin_routes.close_http())
        await _shutdown_gateway_resources()
        logger.info("backend shutdown complete")


app = FastAPI(title="openVman Backend", lifespan=lifespan)


@app.middleware("http")
async def http_metrics_middleware(request: Request, call_next):
    start = monotonic()
    response = await call_next(request)
    endpoint = normalize_http_metrics_endpoint(request)
    if should_record_http_metrics(endpoint):
        duration_ms = (monotonic() - start) * 1000
        record_http_request(
            endpoint=endpoint,
            method=request.method,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
    return response


app.include_router(gateway_router)
app.include_router(internal_router)
app.include_router(brain_proxy_router)
app.include_router(websocket_routes.router)
app.include_router(admin_routes.router)


def _merge_brain_openapi(base_schema: dict, brain_schema: dict) -> dict:
    merged = base_schema.copy()
    
    # Merge paths (remap /brain/ to /api/)
    merged_paths = merged.get("paths", {})
    for path, path_item in brain_schema.get("paths", {}).items():
        if path.startswith("/brain/"):
            merged_paths[path.replace("/brain/", "/api/", 1)] = path_item
    merged["paths"] = merged_paths

    # Merge components (schemas, securitySchemes, etc.)
    merged_comp = merged.get("components", {})
    for sec, vals in brain_schema.get("components", {}).items():
        merged_comp[sec] = {**merged_comp.get(sec, {}), **vals}
    merged["components"] = merged_comp

    # Merge tags
    tags_dict = {t["name"]: t for t in merged.get("tags", []) if "name" in t}
    for tag in brain_schema.get("tags", []):
        if name := tag.get("name"):
            tags_dict[name] = {**tags_dict.get(name, {}), **tag}
    merged["tags"] = list(tags_dict.values())
    
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
    return CachedTTSEntry(
        audio_bytes=result.audio_bytes,
        content_type=result.content_type,
        provider=result.provider,
        route_kind=result.route_kind,
        route_target=result.route_target,
        sample_rate=result.sample_rate,
    )


_openapi_built = False


async def _build_openapi_schema() -> dict:
    global _openapi_built
    if app.openapi_schema is not None:
        return app.openapi_schema

    local_schema = get_openapi(title=app.title, version=app.version, routes=app.routes)

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

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        local_schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        loop.create_task(_build_openapi_schema())
        return local_schema

    return asyncio.run(_build_openapi_schema())


app.openapi = custom_openapi


class SpeechRequest(BaseModel):
    input: str
    voice: str = ""
    provider: str = ""
    response_format: str = "wav"
    speed: float = 1.0

@app.post("/v1/audio/speech", tags=["TTS"], summary="文字轉語音")
async def create_speech(body: SpeechRequest) -> Response:
    cfg = get_tts_config()
    svc = _get_service()
    cleaned_text = clean_for_tts(body.input)
    request = SynthesizeRequest(text=cleaned_text, voice_hint=body.voice)
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
        asyncio.create_task(cache_put(cache_key, _to_cached_tts_entry(output.result), cfg.tts_cache_ttl_seconds))

    return Response(content=output.result.audio_bytes, media_type=output.result.content_type, headers=headers)


@app.post("/documents/convert", tags=["Documents"], summary="文件轉 Markdown")
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
        return JSONResponse(content={"markdown": result.text_content, "page_count": None})
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
    uvicorn.run("app.main:app", host="0.0.0.0", port=cfg.backend_port, reload=cfg.is_dev)


if __name__ == "__main__":
    run_server()

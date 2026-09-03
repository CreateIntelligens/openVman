"""openVman Backend FastAPI entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic

import anydoc
import httpx
from fastapi import Depends, FastAPI, File, Request, Response, UploadFile
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.auth.dependencies import CurrentAccount, get_current_account
from app.auth.middleware import FailClosedAuthMiddleware
from app.auth.embed_key_routes import router as embed_key_router
from app.auth.routes import auth_router, temporary_accounts_router, users_router
from app.auth.runtime import get_auth_runtime
from app.brain_proxy import _http as _brain_proxy_http
from app.brain_proxy import router as brain_proxy_router
from app.config import get_tts_config
from app.error_payloads import upload_failed_response
from app.gateway import websocket as websocket_routes
from app.gateway.crawl_adapter import _http as _crawl_http
from app.gateway.forward import _http as _forward_http
from app.gateway.redis_pool import close_redis, get_redis
from app.gateway.routes import router as gateway_router
from app.gateway.routes_vision import _http as _vision_http
from app.gateway.routes_vision import router as vision_router
from app.gateway.temp_storage import get_temp_storage, reset_temp_storage
from app.gateway.worker import (
    get_api_tool_plugin,
    get_camera_plugin,
    get_web_crawler_plugin,
    reset_plugins,
)
from app.http_client import SharedAsyncClient
from app.internal_routes import _http as _internal_http
from app.internal_routes import router as internal_router
from app.observability import (
    normalize_http_metrics_endpoint,
    record_http_request,
    should_record_http_metrics,
)
from app.project_routes import router as project_router
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.providers.gemini_tts_adapter import (
    GEMINI_STREAM_CONTENT_TYPE,
    GeminiTTSHTTPError,
)
from app.providers.voxcpm_adapter import (
    VOXCPM_PROVIDER_NAME,
    VOXCPM_STREAM_CONTENT_TYPE,
    VoxCPMHTTPError,
)
from app.routes import admin as admin_routes
from app.routes import avatar as avatar_routes
from app.routes import backgrounds as background_routes
from app.routes import mascots as mascot_routes
from app.routes import public_characters as public_characters_routes
from app.routes import static_assets as static_assets_routes
from app.service import TTSRouterService
from app.tts_cache import CachedTTSEntry, cache_get, cache_put, make_cache_key
from app.tts_text import clean_for_tts, prepare_tts_text_async
from app.utils.upload import (
    UploadTooLargeError,
    cleanup_temp_path,
    persist_upload_to_tempfile,
)

logger = logging.getLogger("backend")

_UVICORN_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": "%(asctime)s %(levelprefix)s %(message)s",
            "datefmt": "%H:%M:%S",
            "use_colors": None,
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": '%(asctime)s %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            "datefmt": "%H:%M:%S",
        },
    },
    "handlers": {
        "default": {"formatter": "default", "class": "logging.StreamHandler", "stream": "ext://sys.stderr"},
        "access": {"formatter": "access", "class": "logging.StreamHandler", "stream": "ext://sys.stdout"},
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
    },
}

for _noisy_logger in ("httpx", "httpcore"):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

# 角色影片、VRM、背景圖由瀏覽器分段抓取，一次播放就是幾十行 200/206
_ACCESS_LOG_SILENT_PREFIXES = ("/static/characters/", "/static/mascots/", "/static/backgrounds/")
_ACCESS_LOG_SILENT_PATHS = frozenset({
    "/api/v1/health",
    "/api/v1/health/detailed",
    "/healthz",
    "/api/v1/metrics",
    "/metrics",
    "/metrics/prometheus",
    "/brain/metrics/prometheus",
})
_PLAINTEXT_DOCUMENT_SUFFIXES = frozenset({".md", ".markdown", ".txt"})

_DASHBOARD_POLLING_PATHS = frozenset({
    "/api/v1/projects",
    "/api/v1/personas",
    "/api/v1/tools",
    "/api/v1/knowledge/documents",
    "/api/v1/knowledge/base/documents",
    "/api/v1/memories",
    "/api/v1/sessions",
    "/api/v1/chat/history",
    "/api/v1/tts/providers",
    "/api/v1/knowledge/document",
})


class _SilentAccessPathsFilter(logging.Filter):
    """Drop uvicorn access log lines for infra polling endpoints."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn access log: args = (client, method, path, http_version, status)
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        method = str(args[1])
        path = str(args[2]).split("?")[0]
        status = args[4]

        if status in (200, 206):
            if path in _ACCESS_LOG_SILENT_PATHS:
                return False
            if method == "GET" and path in _DASHBOARD_POLLING_PATHS:
                return False
            if method == "GET" and path.startswith(_ACCESS_LOG_SILENT_PREFIXES):
                return False

        return True


logging.getLogger("uvicorn.access").addFilter(_SilentAccessPathsFilter())

_service: TTSRouterService | None = None
_health_http = SharedAsyncClient()
_BRAIN_OPENAPI_TIMEOUT_SECONDS = 5


def _convert_document_to_markdown(file_path: str) -> str:
    if Path(file_path).suffix.lower() in _PLAINTEXT_DOCUMENT_SUFFIXES:
        return Path(file_path).read_text(encoding="utf-8")
    return anydoc.to_markdown(file_path)


def _get_service() -> TTSRouterService:
    global _service
    _service = _service or TTSRouterService(get_tts_config())
    return _service


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
    runtime = get_auth_runtime()
    await _startup_gateway_resources()
    await _build_openapi_schema()
    await admin_routes.sync_tts_custom_voices(runtime)
    logger.info("backend startup complete")
    try:
        yield
    finally:
        clients = [_brain_proxy_http, _internal_http, _forward_http, _crawl_http, _health_http, _vision_http]
        await asyncio.gather(*(c.close() for c in clients), admin_routes.close_http())
        await _shutdown_gateway_resources()
        logger.info("backend shutdown complete")


app = FastAPI(title="openVman Backend", lifespan=lifespan)
app.add_middleware(FailClosedAuthMiddleware)


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
app.include_router(vision_router)
app.include_router(internal_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(embed_key_router)
app.include_router(temporary_accounts_router)
app.include_router(admin_routes.router)
app.include_router(avatar_routes.router)
app.include_router(public_characters_routes.router)
app.include_router(background_routes.router)
app.include_router(mascot_routes.router)
app.include_router(static_assets_routes.router)
app.include_router(project_router)
app.include_router(websocket_routes.router)


def _merge_brain_openapi(base_schema: dict, brain_schema: dict) -> dict:
    merged = base_schema.copy()
    
    # Merge paths (remap /brain/ to /api/v1/)
    merged_paths = merged.get("paths", {})
    for path, path_item in brain_schema.get("paths", {}).items():
        if path.startswith("/brain/"):
            mapped_path = path.replace("/brain/", "/api/v1/", 1)
            local_path_item = merged_paths.get(mapped_path)
            if local_path_item is None:
                merged_paths[mapped_path] = path_item
                continue

            merged_path_item = path_item.copy()
            for key, local_value in local_path_item.items():
                brain_value = merged_path_item.get(key)
                if isinstance(brain_value, dict) and isinstance(local_value, dict):
                    # Brain fills missing schema fields while the Backend's
                    # public route metadata remains authoritative.
                    merged_path_item[key] = {**brain_value, **local_value}
                else:
                    merged_path_item[key] = local_value
            merged_paths[mapped_path] = merged_path_item
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
async def create_speech(
    body: SpeechRequest,
    current: CurrentAccount = Depends(get_current_account),
) -> Response:
    cfg = get_tts_config()
    authorized = admin_routes.resolve_tts_voice(
        current,
        get_auth_runtime(),
        requested_provider=body.provider,
        requested_voice=body.voice,
    )
    provider = authorized.provider if authorized else body.provider
    voice = authorized.runtime_key if authorized else body.voice
    svc = _get_service()
    cleaned_text = (await prepare_tts_text_async(body.input)) or ""
    request = SynthesizeRequest(text=cleaned_text, voice_hint=voice)
    cache_key: str | None = None

    if cfg.tts_cache_enabled:
        cache_key = make_cache_key(cleaned_text, voice, provider)
        cached = await cache_get(cache_key)
        if cached is not None:
            return _cached_speech_response(cached)

    try:
        output = svc.synthesize(request, provider=provider)
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


class TtsStreamRequest(BaseModel):
    text: str
    character: str = ""
    provider: str = ""
    voice: str = ""


async def _proxy_indextts_stream(
    *,
    indextts_stream_url: str,
    text: str,
    character: str,
) -> StreamingResponse | None:
    cfg = get_tts_config()
    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    try:
        request = client.build_request(
            "POST",
            indextts_stream_url,
            json={"text": text, "character": character},
            headers={"X-Internal-Token": cfg.gateway_internal_token},
        )
        resp = await client.send(request, stream=True)
    except Exception as exc:
        await client.aclose()
        logger.error("tts_stream proxy error: %s", exc)
        return None

    if resp.status_code >= 400:
        detail = ""
        try:
            detail = (await resp.aread()).decode("utf-8", errors="replace")[:500]
        finally:
            await resp.aclose()
            await client.aclose()
        logger.warning(
            "tts_stream indextts error status=%s detail=%s",
            resp.status_code,
            detail,
        )
        return None

    async def _proxy_stream() -> AsyncIterator[bytes]:
        try:
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                if chunk:
                    yield chunk
        except Exception as exc:
            logger.error("tts_stream proxy read error: %s", exc)
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        _proxy_stream(),
        media_type=resp.headers.get("content-type", "audio/wav") or "audio/wav",
    )


@app.post("/api/v1/tts/stream", tags=["TTS"], summary="串流 TTS 合成")
async def tts_stream_endpoint(
    body: TtsStreamRequest,
    current: CurrentAccount = Depends(get_current_account),
) -> Response:
    cfg = get_tts_config()
    authorized = admin_routes.resolve_tts_voice(
        current,
        get_auth_runtime(),
        requested_provider=body.provider,
        requested_voice=body.voice or body.character,
    )
    provider = authorized.provider if authorized else body.provider
    character = authorized.runtime_key if authorized else (body.character or cfg.tts_indextts_default_character)
    voice = authorized.runtime_key if authorized else body.voice
    cleaned = (await prepare_tts_text_async(body.text.strip())) or ""
    if not cleaned:
        return JSONResponse(status_code=400, content={"error": "empty text"})

    # Gemini TTS Console 支援 stream=true，邊生成邊吐 raw PCM（24000Hz），
    # 避免等整段合成完的高延遲。content-type 帶 rate 讓前端知道要重採樣。
    if provider == "gemini-tts":
        svc = _get_service()
        gemini = svc.gemini_adapter
        if gemini.enabled:
            try:
                stream = await gemini.open_stream(
                    SynthesizeRequest(text=cleaned, voice_hint=voice)
                )
            except GeminiTTSHTTPError as exc:
                return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
            except RuntimeError as exc:
                return JSONResponse(status_code=502, content={"error": str(exc)})
            return StreamingResponse(stream, media_type=GEMINI_STREAM_CONTENT_TYPE)

    # provider 未指定（auto）且沒有 IndexTTS 時，VoxCPM 是 fallback 鏈的第一站，
    # 直接走它的串流端點，否則 auto 會掉到整段合成的路徑，前端要等好幾秒。
    if not provider and not cfg.tts_indextts_url and _get_service().voxcpm_adapter.enabled:
        provider = VOXCPM_PROVIDER_NAME

    # VoxCPM 支援 /api/v1/synthesize/stream 串流，邊生成邊吐 48kHz mono WAV。
    if provider == VOXCPM_PROVIDER_NAME:
        voxcpm = _get_service().voxcpm_adapter
        if voxcpm.enabled:
            try:
                stream = await voxcpm.open_stream(
                    SynthesizeRequest(text=cleaned, voice_hint=voice)
                )
                return StreamingResponse(stream, media_type=VOXCPM_STREAM_CONTENT_TYPE)
            except (VoxCPMHTTPError, RuntimeError) as exc:
                # GPU 節點掛掉不該讓整個 TTS 失敗：記一筆後往下走 IndexTTS → Edge 的 fallback。
                logger.warning("tts_stream voxcpm error: %s", exc)

    # Primary: proxy stream directly from IndexTTS
    if cfg.tts_indextts_url:
        indextts_stream_url = cfg.tts_indextts_url.rstrip("/") + "/tts_stream"
        proxied = await _proxy_indextts_stream(
            indextts_stream_url=indextts_stream_url,
            text=cleaned,
            character=character,
        )
        if proxied is not None:
            return proxied

    svc = _get_service()

    # Fallback streaming: Edge-TTS 邊合成邊吐，避免等整句。
    # voice 已經過 resolve_tts_voice 授權；Edge adapter 會把非 Edge 格式的
    # 名稱（例如 IndexTTS 角色名）退回自身預設 voice，這裡不需再清掉。
    edge = svc.edge_adapter
    if edge.enabled:
        stream = edge.synthesize_stream(SynthesizeRequest(text=cleaned, voice_hint=voice))
        return StreamingResponse(stream, media_type="audio/mpeg")

    # Fallback (buffered): 其餘 provider 仍走 service chain 一次性回傳。
    try:
        output = svc.synthesize(
            SynthesizeRequest(text=cleaned, voice_hint=voice or character),
            provider=provider,
        )
    except RuntimeError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})

    return Response(content=output.result.audio_bytes, media_type=output.result.content_type)


@app.post(
    "/api/v1/documents/convert",
    tags=["Documents"],
    summary="文件轉 Markdown",
    description="`.md`、`.markdown`、`.txt` 以 UTF-8 直接讀取；其餘格式使用 Firecrawl AnyDoc 轉換。本端點不保存原始檔，也不觸發知識庫索引。",
)
async def convert(file: UploadFile = File(...)) -> JSONResponse:
    suffix = os.path.splitext(file.filename or "")[1]
    tmp_path: str | None = None
    cfg = get_tts_config()
    try:
        tmp_path, total_bytes = await persist_upload_to_tempfile(
            file,
            suffix=suffix,
            max_bytes=cfg.document_max_upload_bytes,
        )
        logger.info("Converting file: %s (%d bytes)", file.filename, total_bytes)
        markdown = _convert_document_to_markdown(tmp_path)
        from app.utils.chinese import convert_to_traditional
        markdown = convert_to_traditional(markdown or "")
        return JSONResponse(content={"markdown": markdown, "page_count": None})
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


# The Brain proxy owns the `/api/v1/{path:path}` catch-all, so it must be the
# last router registered — Starlette matches routes in declaration order and
# an earlier catch-all would shadow every `@app` endpoint defined above.
app.include_router(brain_proxy_router)


def run_server() -> None:
    import uvicorn

    cfg = get_tts_config()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=cfg.backend_port,
        reload=cfg.is_dev,
        log_config=_UVICORN_LOG_CONFIG,
    )


if __name__ == "__main__":
    run_server()

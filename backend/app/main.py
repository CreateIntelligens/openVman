"""openVman Backend — FastAPI entry point.

Serves TTS synthesis, MarkItDown document conversion, and gateway upload/queue.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI, File, Response, UploadFile
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from markitdown import MarkItDown
from pydantic import BaseModel, Field

from app.brain_proxy import close_client as close_brain_proxy_client
from app.brain_proxy import router as brain_proxy_router
from app.config import get_tts_config
from app.gateway.crawl_adapter import close_client as close_crawl_client
from app.gateway.forward import close_client as close_forward_client
from app.internal_routes import close_client as close_internal_client
from app.internal_routes import router as internal_router
from app.error_payloads import upload_failed_response
from app.gateway.redis_pool import close_redis, get_redis, redis_available
from app.gateway.routes import router as gateway_router
from app.gateway.temp_storage import get_temp_storage, reset_temp_storage
from app.gateway.worker import (
    get_api_tool_plugin,
    get_camera_plugin,
    get_web_crawler_plugin,
    reset_plugins,
)
from app.health_payloads import build_backend_health_payload
from app.observability import get_metrics_snapshot
from app.providers.base import SynthesizeRequest
from app.service import TTSRouterService

logger = logging.getLogger("backend")
_service: TTSRouterService | None = None
_md_converter: MarkItDown | None = None
_health_client: httpx.AsyncClient | None = None
_UPLOAD_CHUNK_SIZE = 1024 * 1024
_BRAIN_OPENAPI_TIMEOUT_SECONDS = 5


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
    global _health_client
    _health_client = httpx.AsyncClient()
    await _startup_gateway_resources()
    await _build_openapi_schema()
    logger.info("backend startup complete")
    try:
        yield
    finally:
        await close_brain_proxy_client()
        await close_internal_client()
        await close_forward_client()
        await close_crawl_client()
        if _health_client is not None:
            await _health_client.aclose()
            _health_client = None
        await _shutdown_gateway_resources()
        logger.info("backend shutdown complete")


app = FastAPI(title="openVman Backend", lifespan=lifespan)

# --- Gateway router ---
app.include_router(gateway_router)

# --- Internal routes (enrich from gateway) ---
app.include_router(internal_router)

# --- Public API facade (/api/* → internal brain service) ---
app.include_router(brain_proxy_router)


def _merge_tag_metadata(existing_tags: list[dict], extra_tags: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: dict[str, int] = {}

    for tag in existing_tags:
        name = str(tag.get("name", "")).strip()
        if not name:
            continue
        seen[name] = len(merged)
        merged.append(tag)

    for tag in extra_tags:
        name = str(tag.get("name", "")).strip()
        if not name:
            continue
        if name in seen:
            merged[seen[name]] = {**merged[seen[name]], **tag}
            continue
        seen[name] = len(merged)
        merged.append(tag)

    return merged


def _merge_component_sections(existing_components: dict, extra_components: dict) -> dict:
    merged = dict(existing_components)
    for section_name, section_values in extra_components.items():
        current_section = dict(merged.get(section_name, {}))
        current_section.update(section_values)
        merged[section_name] = current_section
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
        client = _health_client or httpx.AsyncClient()
        resp = await client.get(brain_openapi_url, timeout=_BRAIN_OPENAPI_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("failed to fetch brain openapi from %s: %s", brain_openapi_url, exc)
        return None


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


def _cleanup_temp_path(path: str | None) -> None:
    if path is None:
        return
    with suppress(FileNotFoundError):
        os.unlink(path)


class UploadTooLargeError(Exception):
    """Raised when an uploaded file exceeds the configured limit."""

    def __init__(self, limit_bytes: int) -> None:
        super().__init__(f"uploaded file too large: limit={limit_bytes}")
        self.limit_bytes = limit_bytes


async def _persist_upload_to_tempfile(
    file: UploadFile,
    *,
    suffix: str,
    max_bytes: int,
) -> tuple[str, int]:
    total_bytes = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
        try:
            while chunk := await file.read(_UPLOAD_CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise UploadTooLargeError(max_bytes)
                tmp.write(chunk)
        except Exception:
            _cleanup_temp_path(tmp_path)
            raise
    return tmp_path, total_bytes


class SpeechRequest(BaseModel):
    """OpenAI-compatible TTS request body."""

    input: str
    voice: str = ""
    response_format: str = "wav"
    speed: float = 1.0


# ---------------------------------------------------------------------------
# Health & metrics
# ---------------------------------------------------------------------------


@app.get("/healthz", tags=["System"])
async def healthz() -> dict:
    storage = get_temp_storage()
    quota = storage.check_quota()
    return await build_backend_health_payload(
        service="tts-router",
        redis_available=await redis_available(),
        quota=quota,
        client=_health_client,
    )


@app.get("/metrics", tags=["System"])
async def metrics() -> dict:
    return get_metrics_snapshot()


# ---------------------------------------------------------------------------
# TTS synthesis
# ---------------------------------------------------------------------------


@app.post("/v1/audio/speech", tags=["TTS"])
async def create_speech(body: SpeechRequest) -> Response:
    svc = _get_service()
    request = SynthesizeRequest(
        text=body.input,
        voice_hint=body.voice,
    )

    try:
        result = svc.synthesize(request)
    except RuntimeError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})

    return Response(
        content=result.audio_bytes,
        media_type=result.content_type,
        headers={
            "X-TTS-Latency-Ms": str(round(result.latency_ms, 2)),
            "X-TTS-Provider": result.provider,
        },
    )


# ---------------------------------------------------------------------------
# MarkItDown — document-to-markdown conversion
# ---------------------------------------------------------------------------


@app.post("/documents/convert", tags=["Documents"])
async def convert(file: UploadFile = File(...)) -> JSONResponse:
    suffix = os.path.splitext(file.filename or "")[1]
    tmp_path: str | None = None
    cfg = get_tts_config()
    try:
        tmp_path, total_bytes = await _persist_upload_to_tempfile(
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
    except UploadTooLargeError:
        return upload_failed_response(
            status_code=413,
            error="uploaded file too large",
        )
    except Exception as exc:
        logger.error("Conversion failed: %s", exc)
        return upload_failed_response(
            status_code=500,
            error=str(exc),
        )
    finally:
        await file.close()
        _cleanup_temp_path(tmp_path)


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

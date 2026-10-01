"""Backend startup and shutdown of shared clients and gateway resources."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth.runtime import get_auth_runtime
from app.brain_proxy import _http as _brain_proxy_http
from app.config import get_tts_config
from app.gateway.a2a_bridge import get_a2a_bridge_daemon
from app.gateway.crawl_adapter import _http as _crawl_http
from app.gateway.forward import _http as _forward_http
from app.gateway.ingestion_audio import _http as _asr_http
from app.gateway.redis_pool import close_redis, get_redis
from app.gateway.routes_vision import _http as _vision_http
from app.gateway.temp_storage import get_temp_storage, reset_temp_storage
from app.gateway.worker import (
    get_api_tool_plugin,
    get_camera_plugin,
    get_web_crawler_plugin,
    reset_plugins,
)
from app.internal_routes import _http as _internal_http
from app.openapi import _health_http
from app.routes import admin as admin_routes

logger = logging.getLogger("backend")


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
    await _app.state.openapi_builder.build()
    admin_routes.sync_asr_engines(runtime)
    await admin_routes.sync_tts_custom_voices(runtime)
    a2a_daemon = get_a2a_bridge_daemon() if get_tts_config().a2a_enabled else None
    if a2a_daemon:
        a2a_daemon.start()
    logger.info("backend startup complete")
    try:
        yield
    finally:
        if a2a_daemon:
            await a2a_daemon.stop()
        clients = [
            _brain_proxy_http, _internal_http, _forward_http,
            _crawl_http, _health_http, _vision_http, _asr_http,
        ]
        await asyncio.gather(*(c.close() for c in clients), admin_routes.close_http())
        await _shutdown_gateway_resources()
        logger.info("backend shutdown complete")

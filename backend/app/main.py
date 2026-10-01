"""Assemble the Backend FastAPI application and run its ASGI server."""

from fastapi import FastAPI

from app import turn_timing as turn_timing_routes
from app.auth.embed_key_routes import router as embed_key_router
from app.auth.middleware import FailClosedAuthMiddleware
from app.auth.routes import (
    auth_router,
    settings_router,
    temporary_accounts_router,
    users_router,
)
from app.brain_proxy import router as brain_proxy_router
from app.config import get_tts_config
from app.gateway import asr_stream as asr_stream_routes
from app.gateway import websocket as websocket_routes
from app.gateway.routes import router as gateway_router
from app.gateway.routes_vision import router as vision_router
from app.http_metrics import http_metrics_middleware
from app.internal_routes import router as internal_router
from app.lifecycle import lifespan
from app.openapi import BackendOpenAPI
from app.project_routes import router as project_router
from app.routes import admin as admin_routes
from app.routes import asr as asr_routes
from app.routes import avatar as avatar_routes
from app.routes import backgrounds as background_routes
from app.routes import documents as document_routes
from app.routes import mascots as mascot_routes
from app.routes import public_characters as public_characters_routes
from app.routes import static_assets as static_assets_routes
from app.routes import tts as tts_routes
from app.server_logging import _UVICORN_LOG_CONFIG, configure_server_logging

configure_server_logging()
app = FastAPI(title="openVman Backend", lifespan=lifespan)
app.add_middleware(FailClosedAuthMiddleware)
app.middleware("http")(http_metrics_middleware)
app.state.openapi_builder = BackendOpenAPI(app)
app.openapi = app.state.openapi_builder.schema

app.include_router(gateway_router)
app.include_router(vision_router)
app.include_router(internal_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(settings_router)
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
app.include_router(asr_stream_routes.router)
app.include_router(turn_timing_routes.router)
app.include_router(tts_routes.router)
app.include_router(document_routes.router)
app.include_router(asr_routes.router)

# The Brain proxy owns the `/api/v1/{path:path}` catch-all, so it must be the
# last router registered — Starlette matches routes in declaration order and
# an earlier catch-all would shadow the local endpoints registered above.
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

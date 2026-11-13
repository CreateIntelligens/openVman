"""大腦層 FastAPI 入口"""

from __future__ import annotations

from fastapi import FastAPI

from config import API_INTERNAL_PORT, get_settings
from infra.client_disconnect import ClientDisconnectMiddleware
from internal_routes import chat_router as internal_chat_router
from internal_routes import router as internal_router
from routes.backups import router as backups_router
from routes.chat import router as chat_router
from routes.health import router as health_router
from routes.knowledge import chat_router as knowledge_chat_router
from routes.knowledge import router as knowledge_router
from routes.knowledge_qa import router as knowledge_qa_router
from routes.memory import router as memory_router
from routes.personas import router as personas_router
from routes.projects import router as projects_router
from routes.protocol import router as protocol_router
from routes.search import router as search_router
from routes.sessions import router as sessions_router
from routes.tools import router as tools_router
from routes.usage import router as usage_router
from routes.workspace import router as workspace_router
from safety.server_http import (
    UVICORN_LOG_CONFIG,
    configure_logging,
    metrics_middleware,
)
from startup import lifespan

configure_logging()

_OPENAPI_TAGS = [
    {"name": "System", "description": "Health, metrics, and identity endpoints."},
    {"name": "Tools & Skills", "description": "Tool registry and skill management APIs."},
    {"name": "Projects", "description": "Project administration endpoints."},
    {"name": "Personas", "description": "Persona listing and administration endpoints."},
    {"name": "Chat", "description": "Chat generation and history endpoints."},
    {"name": "Search & Embeddings", "description": "Embedding generation and semantic search endpoints."},
    {"name": "Memory & Sessions", "description": "Memory storage, maintenance, and session management endpoints."},
    {"name": "Knowledge", "description": "Knowledge document management and indexing endpoints."},
    {"name": "Protocol", "description": "Protocol validation endpoints."},
    {"name": "Internal", "description": "Internal service-to-service endpoints."},
    {"name": "Dreaming", "description": "Background memory consolidation endpoints."},
]


def create_app(role: str | None = None) -> FastAPI:
    role = role or get_settings().brain_role
    if role not in {"admin", "chat"}:
        raise ValueError("unknown Brain role")
    application = FastAPI(
        title="openVman Brain",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/brain/docs",
        redoc_url="/brain/redoc",
        openapi_url="/brain/openapi.json",
        swagger_ui_oauth2_redirect_url="/brain/docs/oauth2-redirect",
        openapi_tags=_OPENAPI_TAGS,
    )
    application.state.brain_role = role
    routers = (
        internal_chat_router, health_router, chat_router,
        search_router, knowledge_chat_router,
    ) if role == "chat" else (
        internal_router, health_router, tools_router, projects_router,
        personas_router, chat_router, search_router, memory_router,
        sessions_router, knowledge_router, knowledge_qa_router,
        workspace_router, protocol_router, usage_router, backups_router,
    )
    for router in routers:
        application.include_router(router)
    application.middleware("http")(metrics_middleware)
    # Outermost middleware must see disconnects before BaseHTTPMiddleware.
    application.add_middleware(ClientDisconnectMiddleware)
    return application


app = create_app()

if __name__ == "__main__":
    import os
    from uuid import uuid4

    import uvicorn

    cfg = get_settings()
    os.environ["BRAIN_METRICS_RUN_ID"] = uuid4().hex
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=API_INTERNAL_PORT,
        reload=cfg.is_dev and cfg.brain_role == "admin",
        workers=cfg.brain_workers,
        log_config=UVICORN_LOG_CONFIG,
    )

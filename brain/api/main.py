"""大腦層 FastAPI 入口"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request

from config import API_INTERNAL_PORT, get_settings
from infra.db import ensure_tables, get_db
from internal_routes import router as internal_router
from knowledge.workspace import ensure_workspace_scaffold
from memory.embedder import get_embedder
from memory.memory_governance import maybe_run_memory_maintenance
from routes.chat import router as chat_router
from routes.health import router as health_router
from routes.knowledge import router as knowledge_router
from routes.memory import router as memory_router
from routes.personas import router as personas_router
from routes.projects import router as projects_router
from routes.protocol import router as protocol_router
from routes.search import router as search_router
from routes.sessions import router as sessions_router
from routes.tools import router as tools_router
from routes.workspace import router as workspace_router
from safety.observability import get_metrics_store, log_event, log_exception

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("brain")

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

_ACCESS_LOG_SILENT_PATHS = frozenset({
    "/brain/health",
    "/brain/health/ready",
    "/brain/health/detailed",
    "/brain/metrics",
    "/brain/metrics/prometheus",
})


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


# ---------------------------------------------------------------------------
# Startup & Lifespan
# ---------------------------------------------------------------------------

async def warmup_resources() -> None:
    """背景預熱重資源，避免第一個請求承擔初始化成本。"""
    logger.info("背景預熱開始...")
    ensure_workspace_scaffold("default")
    await asyncio.to_thread(get_embedder)
    await asyncio.to_thread(ensure_tables, "default")
    await asyncio.to_thread(maybe_run_memory_maintenance, True, "default")
    logger.info("背景預熱完成")


async def load_privacy_filter_if_enabled() -> None:
    """Load Privacy Filter model when enabled, degrading safely on failure."""
    if not get_settings().privacy_filter_enabled:
        return

    from privacy.model import load_privacy_filter_model

    try:
        await asyncio.to_thread(load_privacy_filter_model)
    except Exception as exc:
        logger.warning("Privacy Filter GPU load failed; retrying on CPU: %s", exc)
        from privacy.model import load_privacy_filter_model_cpu
        try:
            await asyncio.to_thread(load_privacy_filter_model_cpu)
        except Exception as cpu_exc:
            logger.warning("Privacy Filter CPU load also failed; regex fallback will be used: %s", cpu_exc)


async def cancel_task(task: asyncio.Task[None] | None) -> None:
    """在 shutdown 時 safe 取消背景任務。"""
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """啟動時先讓服務可用，再背景預熱重資源。"""
    logger.info("初始化大腦層資源...")
    # 確保預設工作區與資料庫連線
    ensure_workspace_scaffold("default")
    get_db("default")

    # 執行資料遷移
    from scripts.migrate_to_projects import run_migration
    await asyncio.to_thread(run_migration)
    await load_privacy_filter_if_enabled()

    # 背景預熱重資源
    app.state.warmup_task = asyncio.create_task(warmup_resources())

    # Start dreaming scheduler (opt-in)
    if get_settings().dreaming_enabled:
        from memory.dreaming.scheduler import start_dreaming_scheduler
        await start_dreaming_scheduler(app)

    logger.info("大腦層就緒")
    yield
    await asyncio.gather(
        cancel_task(getattr(app.state, "dreaming_task", None)),
        cancel_task(getattr(app.state, "warmup_task", None)),
    )


app = FastAPI(
    title="openVman Brain",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/brain/docs",
    redoc_url="/brain/redoc",
    openapi_url="/brain/openapi.json",
    swagger_ui_oauth2_redirect_url="/brain/docs/oauth2-redirect",
    openapi_tags=_OPENAPI_TAGS,
)
for router in (
    internal_router,
    health_router,
    tools_router,
    projects_router,
    personas_router,
    chat_router,
    search_router,
    memory_router,
    sessions_router,
    knowledge_router,
    workspace_router,
    protocol_router,
):
    app.include_router(router)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id", "").strip() or str(uuid4())
    request.state.trace_id = trace_id
    method, path = request.method, request.url.path
    store = get_metrics_store()
    start = perf_counter()

    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Trace-Id"] = trace_id
    except Exception as exc:
        status = 500
        log_exception("http_request_error", exc, trace_id=trace_id, method=method, path=path)
        raise
    finally:
        duration_ms = round((perf_counter() - start) * 1000, 2)
        store.increment("http_requests_total", method=method, path=path, status=status)
        store.observe("http_request_duration_ms", duration_ms, method=method, path=path)
        if path not in _ACCESS_LOG_SILENT_PATHS:
            log_event(
                "http_request",
                trace_id=trace_id, method=method, path=path,
                status=status, duration_ms=duration_ms,
            )

    return response


if __name__ == "__main__":
    import uvicorn

    cfg = get_settings()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=API_INTERNAL_PORT,
        reload=cfg.is_dev,
        log_config=_UVICORN_LOG_CONFIG,
    )

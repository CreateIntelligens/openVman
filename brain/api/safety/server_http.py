"""Brain HTTP tracing, metrics and server logging."""

from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import Request

from safety.http_filters import SilentAccessPathsFilter, is_silent_path
from safety.observability import get_metrics_store, log_event, log_exception


UVICORN_LOG_CONFIG = {
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


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    # Readiness polls should not flood the operator's access log.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").addFilter(SilentAccessPathsFilter())


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

        if not is_silent_path(method, path, status):
            log_event(
                "http_request",
                trace_id=trace_id, method=method, path=path,
                status=status, duration_ms=duration_ms,
            )


    return response

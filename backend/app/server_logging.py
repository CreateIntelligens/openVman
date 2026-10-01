"""Uvicorn formatting and suppression of successful polling access logs."""

import logging

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


def configure_server_logging() -> None:
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, _SilentAccessPathsFilter) for item in access_logger.filters):
        access_logger.addFilter(_SilentAccessPathsFilter())

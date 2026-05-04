import logging

_ACCESS_LOG_SILENT_PATHS = frozenset({
    "/brain/health",
    "/brain/health/ready",
    "/brain/health/detailed",
    "/brain/metrics",
    "/brain/metrics/prometheus",
})

_DASHBOARD_POLLING_PATHS = frozenset({
    "/brain/projects",
    "/brain/personas",
    "/brain/tools",
    "/brain/knowledge/documents",
    "/brain/knowledge/base/documents",
    "/brain/memories",
    "/brain/sessions",
    "/brain/chat/history",
    "/brain/knowledge/document",
})


class SilentAccessPathsFilter(logging.Filter):
    """Drop uvicorn access log lines for infra polling endpoints."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn access log: args = (client, method, path, http_version, status)
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        method = str(args[1])
        path = str(args[2]).split("?")[0]
        status = args[4]
        
        if status == 200:
            if path in _ACCESS_LOG_SILENT_PATHS:
                return False
            if method == "GET" and path in _DASHBOARD_POLLING_PATHS:
                return False
                
        return True


def is_silent_path(method: str, path: str, status: int) -> bool:
    """Check if a request path should be silenced in logs."""
    if status != 200:
        return False
    if path in _ACCESS_LOG_SILENT_PATHS:
        return True
    if method == "GET" and path in _DASHBOARD_POLLING_PATHS:
        return True
    return False

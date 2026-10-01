"""HTTP request metrics middleware."""

from time import monotonic

from fastapi import Request

from app.observability import (
    normalize_http_metrics_endpoint,
    record_http_request,
    should_record_http_metrics,
)


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

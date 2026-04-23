"""TTS routing observability — metrics and structured logging."""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict, deque
from threading import Lock
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

_logger = logging.getLogger("tts_router")
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Lightweight metrics store (mirrors brain/api/safety/observability.py)
# ---------------------------------------------------------------------------

_metrics_lock = Lock()
_counters: dict[str, int] = defaultdict(int)
_TIMING_HISTORY_LIMIT = 256
_HTTP_METRICS_SKIP_ENDPOINTS = frozenset({
    "/healthz",
    "/metrics",
    "/metrics/prometheus",
    "/api/health",
    "/api/metrics",
})


def _new_timing_bucket() -> dict[str, Any]:
    return {
        "count": 0,
        "sum_ms": 0.0,
        "max_ms": 0.0,
        "history": deque(maxlen=_TIMING_HISTORY_LIMIT),
    }


_timings: dict[str, dict[str, Any]] = defaultdict(_new_timing_bucket)
_events: list[dict[str, Any]] = []

# ---------------------------------------------------------------------------
# Prometheus metrics registry (bridge alongside existing in-memory store)
# ---------------------------------------------------------------------------

_prom_ttfb_ms = Histogram(
    "vman_ttfb_ms",
    "Time to first audio byte (ms)",
    buckets=[10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
)
_prom_tts_latency_ms = Histogram(
    "vman_tts_latency_ms",
    "TTS provider end-to-end latency (ms)",
    buckets=[50, 100, 250, 500, 1000, 2500, 5000, 10000],
)
_prom_active_sessions = Gauge("vman_active_sessions", "Active WebSocket sessions")
_prom_error_total = Counter("vman_error_total", "Total errors")
_prom_http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["endpoint", "method", "status_code"],
)
_prom_ws_disconnect_total = Counter("live_ws_disconnect_total", "WebSocket disconnections", ["reason"])
_prom_ws_errors_total = Counter("live_ws_errors_total", "WebSocket errors", ["error_type"])
_prom_ws_reconnect_total = Counter("live_ws_reconnect_total", "WebSocket reconnections")


def log_event(event: str, **fields: Any) -> None:
    """Emit a structured log line and store the event."""
    entry = {"event": event, **fields}
    _logger.info(json.dumps(entry, ensure_ascii=False, default=str))
    with _metrics_lock:
        _events.append(entry)


def increment_counter(name: str, amount: int = 1) -> None:
    with _metrics_lock:
        _counters[name] += amount


def record_timing(name: str, value_ms: float) -> None:
    with _metrics_lock:
        bucket = _timings[name]
        bucket["count"] += 1
        bucket["sum_ms"] += value_ms
        bucket["max_ms"] = max(bucket["max_ms"], value_ms)
        bucket["history"].append(value_ms)


def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def _timing_summary(bucket: dict[str, Any]) -> dict[str, Any]:
    count = int(bucket["count"])
    sum_ms = bucket["sum_ms"]
    values = list(bucket["history"])
    summary = {
        "count": count,
        "sum_ms": sum_ms,
        "avg_ms": round(sum_ms / count, 2) if count else 0.0,
        "min": None,
        "max_ms": bucket["max_ms"],
        "p50": None,
        "p95": None,
        "p99": None,
    }

    if not values:
        return summary

    sorted_values = sorted(values)
    return summary | {
        "min": sorted_values[0],
        "p50": _percentile(sorted_values, 0.50),
        "p95": _percentile(sorted_values, 0.95),
        "p99": _percentile(sorted_values, 0.99),
    }


def get_metrics_snapshot() -> dict[str, Any]:
    """Return a copy of all counters, timings, and events."""
    with _metrics_lock:
        return {
            "counters": dict(_counters),
            "timings": {k: _timing_summary(v) for k, v in _timings.items()},
            "events": list(_events),
        }


def reset_metrics() -> None:
    """Clear all metrics (for testing)."""
    with _metrics_lock:
        _counters.clear()
        _timings.clear()
        _events.clear()


def get_prometheus_sample_value(metric_name: str) -> float:
    """Return the current Prometheus sample value for an unlabeled metric."""
    payload = generate_latest()
    text = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
    prefix = f"{metric_name} "

    for line in text.splitlines():
        if line.startswith(prefix):
            return float(line[len(prefix):].strip())

    return 0.0


def build_prometheus_response() -> Response:
    """Wrap the Prometheus exposition payload in a FastAPI response."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def normalize_http_metrics_endpoint(request: Request) -> str:
    """Prefer the resolved FastAPI route template over the raw URL path."""
    route_path = getattr(request.scope.get("route"), "path", "")
    return route_path or request.url.path


def should_record_http_metrics(endpoint: str) -> bool:
    """Skip health and metrics endpoints to avoid self-observation noise."""
    return endpoint not in _HTTP_METRICS_SKIP_ENDPOINTS


# ---------------------------------------------------------------------------
# TTS routing metrics helpers
# ---------------------------------------------------------------------------

def record_route_attempt(
    *,
    target: str,
    result: str,
    latency_ms: float,
    reason: str = "",
) -> None:
    """Record a single TTS route attempt."""
    increment_counter(f"tts_route_attempts_total|target={target}|result={result}")
    record_timing(f"tts_provider_latency_ms|{target}|{result}", latency_ms)
    _prom_tts_latency_ms.observe(latency_ms)
    if result == "failure":
        increment_counter(f"tts_provider_failures_total|provider={target}|reason={reason}")
        _prom_error_total.inc()
    log_event(
        "tts_route_attempt",
        target=target,
        result=result,
        latency_ms=round(latency_ms, 2),
        reason=reason,
    )


def record_fallback_hop(
    *,
    from_target: str,
    to_target: str,
    reason: str,
) -> None:
    """Record a fallback hop between routes."""
    increment_counter(
        f"tts_fallback_hops_total|from_target={from_target}"
        f"|to_target={to_target}|reason={reason}"
    )
    log_event(
        "tts_fallback_hop",
        from_target=from_target,
        to_target=to_target,
        reason=reason,
    )


def record_chain_exhausted(*, final_reason: str, hops: int) -> None:
    """Record that the entire TTS fallback chain was exhausted."""
    increment_counter(f"tts_chain_exhausted_total|final_reason={final_reason}")
    log_event("tts_chain_exhausted", final_reason=final_reason, hops=hops)


def record_provider_request(*, provider: str, result: str) -> None:
    """Record a provider-level request."""
    increment_counter(f"tts_provider_requests_total|provider={provider}|result={result}")


def record_cache_hit(latency_ms: float) -> None:
    """Record a successful TTS cache lookup."""
    increment_counter("tts_cache_hit")
    record_timing("tts_cache_get_ms", latency_ms)
    log_event("tts_cache_hit", latency_ms=round(latency_ms, 2))


def record_cache_miss(latency_ms: float) -> None:
    """Record a TTS cache miss."""
    increment_counter("tts_cache_miss")
    record_timing("tts_cache_get_ms", latency_ms)
    log_event("tts_cache_miss", latency_ms=round(latency_ms, 2))


def record_cache_store(latency_ms: float) -> None:
    """Record a successful TTS cache write."""
    increment_counter("tts_cache_store")
    record_timing("tts_cache_put_ms", latency_ms)


def record_cache_error(operation: str, error: str) -> None:
    """Record a cache operation failure (operation: 'get' or 'put')."""
    increment_counter("tts_cache_error")
    log_event("tts_cache_error", operation=operation, error=error)


# ---------------------------------------------------------------------------
# Live pipeline metrics helpers
# ---------------------------------------------------------------------------

def set_active_sessions(count: int) -> None:
    """Set the current number of active websocket sessions."""
    with _metrics_lock:
        _counters["live_active_sessions"] = count
    _prom_active_sessions.set(count)


def record_interruption(reason: str = "user") -> None:
    """Record a successful interruption event."""
    increment_counter(f"live_interruptions_total|reason={reason}")
    log_event("live_interruption", reason=reason)


def record_voice_latency(latency_ms: float) -> None:
    """Record user_speak to first-audio latency."""
    record_timing("live_voice_latency_ms", latency_ms)
    _prom_ttfb_ms.observe(latency_ms)
    log_event("live_voice_latency", latency_ms=round(latency_ms, 2))


# ---------------------------------------------------------------------------
# HTTP request metrics helpers
# ---------------------------------------------------------------------------

def record_http_request(*, endpoint: str, method: str, status_code: int, duration_ms: float) -> None:
    """Record an HTTP request with endpoint, method, status code, and duration."""
    increment_counter(f"http_requests_total|endpoint={endpoint}|method={method}|status_code={status_code}")
    record_timing(f"http_request_duration_ms|endpoint={endpoint}|method={method}", duration_ms)
    _prom_http_requests_total.labels(endpoint=endpoint, method=method, status_code=str(status_code)).inc()
    if status_code >= 500:
        increment_counter(f"http_errors_5xx_total|endpoint={endpoint}|method={method}|status_code={status_code}")


# ---------------------------------------------------------------------------
# WebSocket disconnect / reconnect metrics helpers
# ---------------------------------------------------------------------------

def record_ws_disconnect(reason: str = "normal") -> None:
    """Record a WebSocket disconnection."""
    increment_counter(f"live_ws_disconnect_total|reason={reason}")
    _prom_ws_disconnect_total.labels(reason=reason).inc()
    log_event("live_ws_disconnect", reason=reason)


def record_ws_error(error_type: str) -> None:
    """Record an unexpected WebSocket error."""
    increment_counter(f"live_ws_errors_total|error_type={error_type}")
    _prom_ws_errors_total.labels(error_type=error_type).inc()
    _prom_error_total.inc()
    log_event("live_ws_error", error_type=error_type)


def record_ws_reconnect() -> None:
    """Record a WebSocket session reconnect (new session replacing a previous one for same client)."""
    increment_counter("live_ws_reconnect_total")
    _prom_ws_reconnect_total.inc()
    log_event("live_ws_reconnect")

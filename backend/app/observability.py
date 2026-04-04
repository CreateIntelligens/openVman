"""TTS routing observability — metrics and structured logging."""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from threading import Lock
from typing import Any

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
_timings: dict[str, list[float]] = defaultdict(list)
_events: list[dict[str, Any]] = []


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
        _timings[name].append(value_ms)


def get_metrics_snapshot() -> dict[str, Any]:
    """Return a copy of all counters, timings, and events."""
    with _metrics_lock:
        return {
            "counters": dict(_counters),
            "timings": {k: list(v) for k, v in _timings.items()},
            "events": list(_events),
        }


def reset_metrics() -> None:
    """Clear all metrics (for testing)."""
    with _metrics_lock:
        _counters.clear()
        _timings.clear()
        _events.clear()


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
    if result == "failure":
        increment_counter(f"tts_provider_failures_total|provider={target}|reason={reason}")
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


def record_interruption(reason: str = "user") -> None:
    """Record a successful interruption event."""
    increment_counter(f"live_interruptions_total|reason={reason}")
    log_event("live_interruption", reason=reason)


def record_voice_latency(latency_ms: float) -> None:
    """Record user_speak to first-audio latency."""
    record_timing("live_voice_latency_ms", latency_ms)
    log_event("live_voice_latency", latency_ms=round(latency_ms, 2))

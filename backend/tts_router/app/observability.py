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
    kind: str,
    target: str,
    result: str,
    latency_ms: float,
    reason: str = "",
) -> None:
    """Record a single TTS route attempt."""
    increment_counter(f"tts_route_attempts_total|kind={kind}|target={target}|result={result}")
    record_timing(f"tts_provider_latency_ms|{kind}:{target}|{result}", latency_ms)
    if result == "failure":
        increment_counter(f"tts_provider_failures_total|provider={target}|reason={reason}")
    log_event(
        "tts_route_attempt",
        kind=kind,
        target=target,
        result=result,
        latency_ms=round(latency_ms, 2),
        reason=reason,
    )


def record_fallback_hop(
    *,
    from_kind: str,
    from_target: str,
    to_kind: str,
    to_target: str,
    reason: str,
) -> None:
    """Record a fallback hop between routes."""
    increment_counter(
        f"tts_fallback_hops_total|from_kind={from_kind}|from_target={from_target}"
        f"|to_kind={to_kind}|to_target={to_target}|reason={reason}"
    )
    log_event(
        "tts_fallback_hop",
        from_kind=from_kind,
        from_target=from_target,
        to_kind=to_kind,
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


# ---------------------------------------------------------------------------
# Node-specific metrics helpers (TASK-13)
# ---------------------------------------------------------------------------

def record_node_selected(*, node_id: str, role: str, score: int) -> None:
    """Record that a node was selected for synthesis."""
    increment_counter(f"tts_node_selected_total|node_id={node_id}|role={role}")
    log_event("tts_node_selected", node_id=node_id, role=role, score=score)


def record_node_bypassed(*, node_id: str, reason: str) -> None:
    """Record that a node was bypassed (unhealthy or in cooldown)."""
    increment_counter(f"tts_node_bypassed_total|node_id={node_id}|reason={reason}")
    log_event("tts_node_bypassed", node_id=node_id, reason=reason)


def record_node_failover(*, from_node: str, to_target: str, reason: str) -> None:
    """Record failover from one node to another target."""
    increment_counter(
        f"tts_node_failover_total|from_node={from_node}|to_target={to_target}"
    )
    log_event(
        "tts_node_failover",
        from_node=from_node,
        to_target=to_target,
        reason=reason,
    )

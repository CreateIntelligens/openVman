"""Structured logging and lightweight in-process metrics."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from threading import Lock
from time import time
from typing import Any

logger = logging.getLogger("brain")


class MetricsStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._timings: dict[str, dict[str, float]] = defaultdict(
            lambda: {"count": 0, "sum_ms": 0.0, "max_ms": 0.0}
        )

    def increment(self, name: str, value: int = 1, **labels: object) -> None:
        with self._lock:
            self._counters[_metric_key(name, labels)] += value

    def observe(self, name: str, value_ms: float, **labels: object) -> None:
        with self._lock:
            bucket = self._timings[_metric_key(name, labels)]
            bucket["count"] += 1
            bucket["sum_ms"] += value_ms
            bucket["max_ms"] = max(bucket["max_ms"], value_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            timings = {
                key: {
                    **value,
                    "avg_ms": round(value["sum_ms"] / value["count"], 2) if value["count"] else 0.0,
                }
                for key, value in self._timings.items()
            }
            return {
                "counters": dict(self._counters),
                "timings": timings,
            }


_metrics: MetricsStore | None = None


def get_metrics_store() -> MetricsStore:
    global _metrics
    if _metrics is None:
        _metrics = MetricsStore()
    return _metrics


def log_event(event: str, **fields: object) -> None:
    payload = {
        "ts": int(time()),
        "event": event,
        **fields,
    }
    logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def log_exception(event: str, exc: Exception, **fields: object) -> None:
    payload = {
        "ts": int(time()),
        "event": event,
        "error_type": type(exc).__name__,
        "error": str(exc),
        **fields,
    }
    logger.exception(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _metric_key(name: str, labels: dict[str, object]) -> str:
    if not labels:
        return name
    serialized = ",".join(f"{key}={labels[key]}" for key in sorted(labels))
    return f"{name}|{serialized}"


# ---------------------------------------------------------------------------
# Routing metrics helpers (TASK-24)
# ---------------------------------------------------------------------------

def record_route_attempt(
    *,
    trace_id: str,
    provider: str,
    model: str,
    hop_index: int,
    result: str,
    latency_ms: float,
    reason: str = "",
    chain_length: int = 0,
) -> None:
    """Record a routing attempt with metrics and structured log."""
    store = get_metrics_store()
    store.increment("llm_route_attempts_total", provider=provider, model=model, result=result)
    store.observe("llm_route_latency_ms", latency_ms, provider=provider, model=model, result=result)

    if result == "failure" and reason:
        store.increment("llm_provider_failures_total", provider=provider, model=model, reason=reason)

    log_event(
        "llm_route_attempt",
        trace_id=trace_id,
        provider=provider,
        model=model,
        hop_index=hop_index,
        result=result,
        reason=reason,
        latency_ms=round(latency_ms, 2),
        chain_length=chain_length,
    )


def record_fallback_hop(
    *,
    trace_id: str,
    from_provider: str,
    from_model: str,
    to_provider: str,
    to_model: str,
    reason: str,
    hop_index: int,
) -> None:
    """Record a fallback hop between providers/models."""
    store = get_metrics_store()
    store.increment(
        "llm_fallback_hops_total",
        from_provider=from_provider,
        from_model=from_model,
        to_provider=to_provider,
        to_model=to_model,
        reason=reason,
    )
    log_event(
        "llm_fallback_hop",
        trace_id=trace_id,
        from_provider=from_provider,
        from_model=from_model,
        to_provider=to_provider,
        to_model=to_model,
        reason=reason,
        hop_index=hop_index,
    )


def record_chain_exhausted(*, trace_id: str, final_reason: str, hops: int) -> None:
    """Record that the entire fallback chain was exhausted."""
    store = get_metrics_store()
    store.increment("llm_chain_exhausted_total", final_reason=final_reason)
    log_event(
        "llm_chain_exhausted",
        trace_id=trace_id,
        final_reason=final_reason,
        total_hops=hops,
    )


def record_circuit_state_change(
    *, provider: str, old_state: str, new_state: str
) -> None:
    """Record a circuit-breaker state transition."""
    store = get_metrics_store()
    store.increment(
        "llm_circuit_breaker_state_changes_total",
        provider=provider,
        state=new_state,
    )
    log_event(
        f"llm_circuit_{new_state}",
        provider=provider,
        old_state=old_state,
        new_state=new_state,
    )

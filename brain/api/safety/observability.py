"""Structured logging and lightweight in-process metrics."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from threading import Lock
from time import time
from typing import Any

logger = logging.getLogger("brain")

MetricLabels = tuple[tuple[str, str], ...]
MetricSeriesKey = tuple[str, MetricLabels]


class MetricsStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[MetricSeriesKey, int] = defaultdict(int)
        self._timings: dict[MetricSeriesKey, dict[str, float]] = defaultdict(
            lambda: {"count": 0, "sum_ms": 0.0, "max_ms": 0.0}
        )

    def increment(self, name: str, value: int = 1, **labels: object) -> None:
        with self._lock:
            self._counters[(name, _metric_labels(labels))] += value

    def observe(self, name: str, value_ms: float, **labels: object) -> None:
        with self._lock:
            bucket = self._timings[(name, _metric_labels(labels))]
            bucket["count"] += 1
            bucket["sum_ms"] += value_ms
            bucket["max_ms"] = max(bucket["max_ms"], value_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            timings = {
                _metric_key(name, labels): {
                    **value,
                    "avg_ms": round(value["sum_ms"] / value["count"], 2) if value["count"] else 0.0,
                }
                for (name, labels), value in self._timings.items()
            }
            return {
                "counters": {
                    _metric_key(name, labels): value
                    for (name, labels), value in self._counters.items()
                },
                "timings": timings,
            }

    def iter_counters(self) -> list[tuple[str, dict[str, str], int]]:
        with self._lock:
            return [
                (name, dict(labels), value)
                for (name, labels), value in self._counters.items()
            ]

    def iter_timings(self) -> list[tuple[str, dict[str, str], dict[str, float]]]:
        with self._lock:
            return [
                (name, dict(labels), dict(value))
                for (name, labels), value in self._timings.items()
            ]


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


def _metric_labels(labels: dict[str, object]) -> MetricLabels:
    return tuple((key, str(labels[key])) for key in sorted(labels))


def _metric_key(name: str, labels: dict[str, object] | MetricLabels) -> str:
    label_items = _metric_labels(labels) if isinstance(labels, dict) else labels
    if not label_items:
        return name
    serialized = ",".join(f"{key}={value}" for key, value in label_items)
    return f"{name}|{serialized}"


def render_prometheus(store: MetricsStore | None = None) -> bytes:
    """Render metrics using prometheus_client instead of hand-built text output."""
    from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest

    metrics_store = store or get_metrics_store()
    registry = CollectorRegistry()
    # Key by (cls, metric_name) only so that label-set inconsistencies across
    # call sites (e.g. different subsets of label keys for the same metric)
    # do not cause a duplicate-registration ValueError in the local registry.
    _created: dict[tuple[type, str], Any] = {}

    def _get_or_create(cls, metric_name: str, labelnames: tuple[str, ...]):
        key = (cls, metric_name)
        if key not in _created:
            _created[key] = cls(metric_name, metric_name, labelnames=labelnames, registry=registry)
        return _created[key]

    for metric_name, labels, value in metrics_store.iter_counters():
        labelnames = tuple(labels)
        metric = _get_or_create(Counter, metric_name, labelnames)
        child = metric.labels(**labels) if labelnames else metric
        child.inc(value)

    for metric_name, labels, bucket in metrics_store.iter_timings():
        labelnames = tuple(labels)
        for suffix, field in (("_count", "count"), ("_sum", "sum_ms"), ("_max", "max_ms")):
            gauge = _get_or_create(Gauge, f"{metric_name}{suffix}", labelnames)
            child = gauge.labels(**labels) if labelnames else gauge
            child.set(bucket[field])

    return generate_latest(registry)


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
    **details: object,
) -> None:
    """Record a routing attempt with metrics and structured log.

    The log line also carries the node-attempt fields every answer-path node
    shares (``node``, ``outcome``, ``elapsed_ms``), plus *details* such as
    ``mode``, ``timeout_s``, ``error_type``, ``streamed_chars``.
    """
    store = get_metrics_store()
    store.increment("llm_route_attempts_total", provider=provider, model=model, result=result)
    store.observe("llm_route_latency_ms", latency_ms, provider=provider, model=model, result=result)

    if result == "failure" and reason:
        store.increment("llm_provider_failures_total", provider=provider, model=model, reason=reason)

    log_event(
        "llm_route_attempt",
        trace_id=trace_id,
        node="llm_hop",
        provider=provider,
        model=model,
        hop_index=hop_index,
        result=result,
        outcome="ok" if result == "success" else (reason or result),
        reason=reason,
        latency_ms=round(latency_ms, 2),
        elapsed_ms=round(latency_ms, 2),
        chain_length=chain_length,
        **details,
    )


def record_node_attempt(
    node: str,
    *,
    outcome: str,
    elapsed_ms: float,
    component: str = "",
    timeout_s: float | None = None,
    trace_id: str | None = None,
    exc: BaseException | None = None,
    **fields: object,
) -> None:
    """One structured event per attempt of an answer-path node (RAG, tool, budget).

    *outcome* is ``ok`` / ``empty`` / ``timeout`` / ``error`` / ``skipped``; the
    event says which node, how long it waited and under which limit, so a slow
    turn can be traced to the node that held it up.
    """
    from core.turn_budget import current_trace_id, error_fields

    store = get_metrics_store()
    store.increment("node_attempts_total", node=node, outcome=outcome)
    store.observe("node_attempt_ms", elapsed_ms, node=node, outcome=outcome)
    payload: dict[str, object] = {
        "node": node,
        "outcome": outcome,
        "elapsed_ms": round(elapsed_ms, 2),
        "trace_id": trace_id if trace_id is not None else current_trace_id(),
    }
    if component:
        payload["component"] = component
    if timeout_s is not None:
        payload["timeout_s"] = round(timeout_s, 3)
    payload.update(error_fields(exc))
    payload.update(fields)
    log_event("node_attempt", **payload)


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

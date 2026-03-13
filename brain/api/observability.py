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

"""Request-local timing for serial calls in a single thread.

This profiler does not support use across threads or concurrent tasks. Names
must be fixed stage labels: never pass queries, source text or identifiers.
Create one instance per request, or reset after all measurements have exited.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import math
from time import perf_counter


def _covered_ms(intervals: list[tuple[float, float]]) -> float:
    """Count a union of intervals once, even when descendants overlap."""
    covered = 0.0
    end = None
    for start, stop in sorted(intervals):
        if end is None or start >= end:
            covered += stop - start
        elif stop > end:
            covered += stop - end
        end = stop if end is None else max(end, stop)
    return covered


class Profiler:
    """Measure nested stages with a seconds-based monotonic injected clock.

    ``parent`` is the enclosing span's zero-based index in ``spans``, or None.
    Inclusive totals sum each invocation; self totals exclude the union of all
    descendant intervals, so a child containing a grandchild is deducted once.
    ``report`` returns detached JSON-safe data only after all spans close.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = perf_counter,
        request_started_at: float | None = None,
    ) -> None:
        self._clock = clock
        self._stack: list[int] = []
        self.reset(request_started_at=request_started_at)

    def reset(self, *, request_started_at: float | None = None) -> None:
        """Start a fresh request; reject reset during an active measurement."""
        if self._stack:
            raise RuntimeError("Cannot reset while measurements are active")
        origin = self._clock() if request_started_at is None else request_started_at
        if not math.isfinite(origin):
            raise ValueError("Request clock origin must be finite")
        self._origin = origin
        self._last_ms = 0.0
        self._spans: list[dict] = []

    def _elapsed_ms(self) -> float:
        elapsed = (self._clock() - self._origin) * 1000
        if not math.isfinite(elapsed) or elapsed < self._last_ms:
            raise ValueError("Clock must be finite and monotonic")
        self._last_ms = elapsed
        return elapsed

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        """Record one stage even when its body raises, without suppressing it."""
        if not isinstance(name, str) or not name:
            raise ValueError("Stage name must be a nonempty string")
        span = {
            "name": name,
            "start_ms": self._elapsed_ms(),
            "end_ms": None,
            "duration_ms": None,
            "parent": self._stack[-1] if self._stack else None,
        }
        index = len(self._spans)
        self._spans.append(span)
        self._stack.append(index)
        try:
            yield
        finally:
            try:
                span["end_ms"] = self._elapsed_ms()
                span["duration_ms"] = span["end_ms"] - span["start_ms"]
            finally:
                self._stack.pop()

    def report(self) -> dict:
        """Return per-name count/inclusive/self milliseconds and full spans."""
        if self._stack:
            raise RuntimeError("Cannot report while measurements are active")
        if any(span["end_ms"] is None for span in self._spans):
            raise RuntimeError("A measurement failed; reset before reporting")
        descendants: list[list[tuple[float, float]]] = [
            [] for _ in self._spans
        ]
        for span in self._spans:
            parent = span["parent"]
            while parent is not None:
                descendants[parent].append((span["start_ms"], span["end_ms"]))
                parent = self._spans[parent]["parent"]
        summary = {}
        for index, span in enumerate(self._spans):
            totals = summary.setdefault(span["name"], {
                "count": 0, "inclusive_ms": 0.0, "self_ms": 0.0,
            })
            totals["count"] += 1
            totals["inclusive_ms"] += span["duration_ms"]
            totals["self_ms"] += max(
                0.0, span["duration_ms"] - _covered_ms(descendants[index]),
            )
        return {"summary": summary, "spans": [dict(s) for s in self._spans]}

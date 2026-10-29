"""Measure request latency through the main TextDeltaListener protocol."""

from collections.abc import Callable
from time import perf_counter


class LatencyProbe:
    """Track the final provider attempt without retaining answer text in output.

    ``request_started_at`` and ``clock`` must use the same seconds-based clock.
    Supply the request start before retrieval to include retrieval in both times.
    Methods follow TextDeltaListener and are called serially by the generation
    thread; call ``finish`` after generation completes.
    """

    def __init__(
        self,
        *,
        request_started_at: float | None = None,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._clock = clock
        self._request_started_at = (
            clock() if request_started_at is None else request_started_at
        )
        self._stream_attempts = 0
        self._first_text_at: float | None = None
        self._deltas: list[str] = []

    def attempt_started(self) -> None:
        """Discard fallback or tool-round text before the next provider attempt."""
        self._stream_attempts += 1
        self._first_text_at = None
        self._deltas = []

    def text_delta(self, delta: str) -> None:
        """Record the first non-whitespace text of the current attempt."""
        self._deltas.append(delta)
        if self._first_text_at is None and delta.strip():
            self._first_text_at = self._clock()

    def finish(self, final_answer: str) -> dict[str, float | int | bool | None]:
        """Return millisecond timings, validating streaming against the answer.

        Edge whitespace is ignored for matching because provider replies are
        stripped before returning. A partial or replaced answer has no valid
        first-text latency, even when some text was streamed earlier.
        """
        finished_at = self._clock()
        stream_matches_final = (
            self._first_text_at is not None
            and "".join(self._deltas).strip() == final_answer.strip()
        )
        first_text_ms = None
        if stream_matches_final and self._first_text_at is not None:
            first_text_ms = (
                self._first_text_at - self._request_started_at
            ) * 1000
        return {
            "first_text_ms": first_text_ms,
            "total_ms": (finished_at - self._request_started_at) * 1000,
            "stream_attempts": self._stream_attempts,
            "stream_matches_final": stream_matches_final,
        }

"""In-memory sliding-window limit on failed password checks per account."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from math import ceil
from threading import Lock


class FailedAttemptLimiter:
    """Lock a key after too many failures inside a sliding window.

    展示機台的解鎖密碼是在現場、任何訪客都摸得到的螢幕上輸入，所以要擋暴力
    嘗試。只放記憶體：重啟歸零可以接受，多副本時各自計數也只是放寬上限。
    """

    def __init__(
        self,
        *,
        max_failures: int = 5,
        window_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_failures = max_failures
        self._window_seconds = window_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> deque[float] | None:
        failures = self._failures.get(key)
        if failures is None:
            return None
        while failures and now - failures[0] >= self._window_seconds:
            failures.popleft()
        if not failures:
            del self._failures[key]
            return None
        return failures

    def retry_after(self, key: str) -> int | None:
        """Seconds until ``key`` may try again, or None when not locked."""
        with self._lock:
            now = self._clock()
            failures = self._prune(key, now)
            if failures is None or len(failures) < self._max_failures:
                return None
            # 視窗內第一次失敗滑出去之後才會低於上限。
            oldest = failures[-self._max_failures]
            return max(1, ceil(oldest + self._window_seconds - now))

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            self._prune(key, now)
            self._failures.setdefault(key, deque()).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

"""Sliding-window limit on failed checks per key, in memory or shared through Redis."""

from __future__ import annotations

import time
import uuid
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


class RedisAttemptLimiter:
    """The same sliding window shared through Redis by every Backend process.

    Backend 開多個 process 時，記憶體版各算各的，上限等於乘上 process 數；
    改存 Redis 的 sorted set，每次失敗一筆、分數是時間。Redis 連不上時退回
    這個 process 自己的記憶體版，限流仍有作用，只是暫時各自計數。
    """

    def __init__(
        self,
        client,
        namespace: str,
        *,
        max_failures: int = 5,
        window_seconds: float = 300.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._redis = client
        self._namespace = namespace
        self._max_failures = max_failures
        self._window_seconds = window_seconds
        self._clock = clock
        self._local = FailedAttemptLimiter(
            max_failures=max_failures, window_seconds=window_seconds,
        )

    def _key(self, key: str) -> str:
        return f"vman:attempts:{self._namespace}:{key}"

    def retry_after(self, key: str) -> int | None:
        now = self._clock()
        name = self._key(key)
        try:
            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(name, "-inf", now - self._window_seconds)
            pipe.zcard(name)
            _, count = pipe.execute()
            if count < self._max_failures:
                return None
            # 視窗內第一次失敗滑出去之後才會低於上限。
            oldest = self._redis.zrange(name, count - self._max_failures, count - self._max_failures, withscores=True)
        except Exception:  # noqa: BLE001 - Redis 掛掉時仍要限流
            return self._local.retry_after(key)
        if not oldest:
            return None
        return max(1, ceil(oldest[0][1] + self._window_seconds - now))

    def record_failure(self, key: str) -> None:
        now = self._clock()
        name = self._key(key)
        try:
            pipe = self._redis.pipeline()
            pipe.zadd(name, {f"{now:.6f}:{uuid.uuid4().hex}": now})
            pipe.expire(name, ceil(self._window_seconds) + 1)
            pipe.execute()
        except Exception:  # noqa: BLE001
            self._local.record_failure(key)

    def reset(self, key: str) -> None:
        try:
            self._redis.delete(self._key(key))
        except Exception:  # noqa: BLE001
            pass
        self._local.reset(key)

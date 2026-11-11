"""Bounded query-vector reuse and thread-safe coalescing within one worker."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from copy import deepcopy
from threading import Lock
from typing import Generic, TypeVar

T = TypeVar("T")


class QueryEmbeddingCache(Generic[T]):
    def __init__(self) -> None:
        self._lock = Lock()
        self._entries: OrderedDict[tuple[object, ...], T] = OrderedDict()
        self._pending: dict[tuple[object, ...], Future[T]] = {}

    def get_or_compute(
        self,
        key: tuple[object, ...],
        compute: Callable[[], T],
        *,
        max_entries: int,
        wait_timeout: float,
        cacheable: Callable[[T], bool],
    ) -> tuple[T, str]:
        if max_entries <= 0:
            return compute(), "disabled"

        with self._lock:
            while len(self._entries) > max_entries:
                self._entries.popitem(last=False)
            if key in self._entries:
                value = self._entries[key]
                self._entries.move_to_end(key)
                return deepcopy(value), "hit"
            future = self._pending.get(key)
            leader = future is None
            if future is None:
                future = Future()
                self._pending[key] = future

        if not leader:
            # A short-budget waiter must not cancel work other turns still need.
            return deepcopy(future.result(timeout=wait_timeout)), "coalesced"

        try:
            value = compute()
            snapshot = deepcopy(value)
            with self._lock:
                if cacheable(value):
                    self._entries[key] = snapshot
                    while len(self._entries) > max_entries:
                        self._entries.popitem(last=False)
                future.set_result(snapshot)
                del self._pending[key]
            return value, "miss"
        except BaseException as exc:
            with self._lock:
                future.set_exception(exc)
                del self._pending[key]
            raise

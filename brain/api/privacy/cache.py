"""In-process LRU cache for privacy detection counts."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from threading import Lock

FilterResult = dict[str, int]


class PrivacyFilterCache:
    """Thread-safe bounded LRU cache keyed by content hash."""

    def __init__(self, max_entries: int = 512) -> None:
        self._max_entries = max(1, int(max_entries))
        self._store: OrderedDict[str, FilterResult] = OrderedDict()
        self._lock = Lock()

    def get(self, content: str) -> FilterResult | None:
        key = _cache_key(content)
        with self._lock:
            value = self._store.get(key)
            if value is None:
                return None
            self._store.move_to_end(key)
            return dict(value)

    def set(self, content: str, result: FilterResult) -> None:
        key = _cache_key(content)
        with self._lock:
            self._store[key] = dict(result)
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)


def _cache_key(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


_cache: PrivacyFilterCache | None = None
_cache_size = 0
_cache_lock = Lock()


def get_privacy_filter_cache(max_entries: int) -> PrivacyFilterCache:
    """Return a module-level cache sized for the current config."""
    global _cache, _cache_size
    normalized_size = max(1, int(max_entries))
    if _cache is None or _cache_size != normalized_size:
        with _cache_lock:
            if _cache is None or _cache_size != normalized_size:
                _cache = PrivacyFilterCache(normalized_size)
                _cache_size = normalized_size
    return _cache

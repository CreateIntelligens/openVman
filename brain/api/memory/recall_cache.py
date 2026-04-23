"""In-memory TTL cache for auto recall summaries."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic

from config import get_settings


@dataclass(slots=True)
class RecallCacheEntry:
    """A single cached recall summary."""

    summary: str
    expires_at: float  # monotonic timestamp
    inserted_at: float  # monotonic timestamp


class RecallCache:
    """Thread-safe, TTL-aware, bounded FIFO recall cache."""

    def __init__(self, *, ttl_ms: int | None = None, max_entries: int | None = None) -> None:
        cfg = get_settings()
        self._ttl_s = (ttl_ms or cfg.auto_recall_cache_ttl_ms) / 1000.0
        self._max_entries = max_entries or cfg.auto_recall_max_cache_entries
        self._store: OrderedDict[str, RecallCacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> str | None:
        """Return cached summary if *key* exists and is not expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if monotonic() >= entry.expires_at:
                self._store.pop(key, None)
                return None
            return entry.summary

    def set(self, key: str, summary: str) -> None:
        """Store *summary* under *key* with current TTL."""
        now = monotonic()
        with self._lock:
            # Remove existing so re-insert goes to end
            self._store.pop(key, None)
            self._store[key] = RecallCacheEntry(
                summary=summary,
                expires_at=now + self._ttl_s,
                inserted_at=now,
            )
            # FIFO eviction
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def sweep_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        now = monotonic()
        removed = 0
        with self._lock:
            expired_keys = [k for k, v in self._store.items() if now >= v.expires_at]
            for k in expired_keys:
                del self._store[k]
                removed += 1
        return removed


# ------------------------------------------------------------------
# Cache key helper
# ------------------------------------------------------------------

def make_cache_key(session_id: str, query_text: str) -> str:
    """Deterministic cache key: truncated SHA-256 of session_id + query."""
    raw = f"{session_id}:{query_text}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_recall_cache: RecallCache | None = None
_singleton_lock = threading.Lock()


def get_recall_cache() -> RecallCache:
    """Return the module-level RecallCache singleton."""
    global _recall_cache
    if _recall_cache is None:
        with _singleton_lock:
            if _recall_cache is None:
                _recall_cache = RecallCache()
    return _recall_cache

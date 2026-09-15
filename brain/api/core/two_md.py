"""Shared contracts and local coordination primitives for 2MD web tools."""

from __future__ import annotations

import hashlib
import json
import random
import secrets
from dataclasses import dataclass
from threading import Event, Lock
from typing import Any, Callable, TypeVar
from urllib.parse import urlparse

from .two_md_defaults import TWO_MD_BASE_URLS


T = TypeVar("T")

def _validate_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"2MD base URL 不合法: {value!r}")
    return normalized


def resolve_base_urls(cfg: Any) -> tuple[str, ...]:
    """Resolve a complete endpoint list, retaining legacy config compatibility."""
    raw = str(getattr(cfg, "url2md_base_urls", "") or "").strip()
    if raw:
        values = [item.strip() for item in raw.split(",") if item.strip()]
    else:
        legacy = [
            str(getattr(cfg, "url2md_primary_url", "") or "").strip(),
            *str(getattr(cfg, "url2md_fallback_urls", "") or "").split(","),
        ]
        values = [item.strip() for item in legacy if item.strip()]
    if not values:
        return TWO_MD_BASE_URLS
    resolved = tuple(dict.fromkeys(_validate_base_url(value) for value in values))
    if not resolved:
        raise ValueError("至少需要一個 2MD base URL")
    return resolved


def build_operation_key(
    operation: str,
    payload: dict[str, Any],
    *,
    response_policy: str,
    privacy_scope: str,
) -> str:
    """Build a stable hash key without putting user text in coordination stores."""
    normalized = dict(payload)
    if isinstance(normalized.get("query"), str):
        normalized["query"] = " ".join(normalized["query"].split())
    if isinstance(normalized.get("urls"), list):
        normalized["urls"] = sorted(
            {str(url).strip().rstrip("/") for url in normalized["urls"] if str(url).strip()}
        )
    raw = json.dumps(
        {
            "operation": operation,
            "payload": normalized,
            "response_policy": response_policy,
            "privacy_scope": privacy_scope,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def full_jitter_delay(
    attempt: int,
    *,
    base_s: float,
    max_s: float,
    remaining_s: float | None,
    random_value: float | None = None,
) -> float:
    """Return bounded full-jitter delay for an attempt."""
    cap = min(max_s, base_s * (2 ** max(0, attempt - 1)))
    sample = random.random() if random_value is None else min(1.0, max(0.0, random_value))
    delay = max(0.0, cap) * sample
    if remaining_s is not None:
        delay = min(delay, max(0.0, remaining_s))
    return delay


@dataclass
class _Flight:
    event: Event
    result: Any = None
    error: BaseException | None = None


class SingleFlight:
    """Coalesce identical in-process read-only operations."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._flights: dict[str, _Flight] = {}

    def run(
        self,
        key: str,
        operation: Callable[[], T],
        *,
        timeout_s: float,
        on_coalesced: Callable[[], None] | None = None,
    ) -> T:
        with self._lock:
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                flight = _Flight(event=Event())
                self._flights[key] = flight
        assert flight is not None

        if not leader:
            if on_coalesced is not None:
                on_coalesced()
            if not flight.event.wait(max(0.0, timeout_s)):
                raise TimeoutError("等待相同 2MD 請求結果逾時")
            if flight.error is not None:
                raise flight.error
            return flight.result

        try:
            flight.result = operation()
            return flight.result
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._flights.pop(key, None)
            flight.event.set()


class RedisCoordination:
    """Optional cross-instance circuit and probe lease coordination.

    This class stores only endpoint state and short-lived leases. It never stores
    queries, URLs, or fetched response bodies.
    """

    _RELEASE_SCRIPT = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('del', KEYS[1])
    end
    return 0
    """

    def __init__(self, redis_url: str, *, namespace: str = "brain:url2md", client: Any = None) -> None:
        self._namespace = namespace.strip(":") or "brain:url2md"
        self._token = secrets.token_hex(16)
        self._client = client
        self._available = client is not None
        if self._client is None and redis_url.strip():
            try:
                import redis

                self._client = redis.Redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=0.5,
                    socket_timeout=0.5,
                )
                self._client.ping()
            except Exception:
                self._client = None
                self._available = False

    @property
    def configured(self) -> bool:
        return self._available and self._client is not None

    def _key(self, kind: str, endpoint: str) -> str:
        endpoint_hash = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:24]
        return f"{self._namespace}:{kind}:{endpoint_hash}"

    def endpoint_allowed(self, endpoint: str, *, cooldown_s: float, lease_s: float) -> bool:
        """Check a shared circuit and acquire the sole half-open probe lease."""
        if not self.configured:
            return True
        circuit_key = self._key("circuit", endpoint)
        recovery_key = self._key("recovery", endpoint)
        try:
            if self._client.exists(circuit_key):
                return False
            if not self._client.exists(recovery_key):
                return True
            # The circuit key expires after cooldown. During half-open, exactly
            # one caller owns the probe lease; others skip this endpoint.
            return bool(
                self._client.set(
                    self._key("probe", endpoint),
                    self._token,
                    nx=True,
                    px=max(1, int(lease_s * 1000)),
                )
            )
        except Exception:
            self._available = False
            return True

    def mark_failure(self, endpoint: str, *, cooldown_s: float) -> None:
        if not self.configured:
            return
        try:
            self._client.set(
                self._key("circuit", endpoint),
                "open",
                px=max(1, int(cooldown_s * 1000)),
            )
            self._client.set(
                self._key("recovery", endpoint),
                "ready",
                px=max(1, int((cooldown_s + 2) * 1000)),
            )
        except Exception:
            self._available = False
            return

    def mark_success(self, endpoint: str) -> None:
        if not self.configured:
            return
        probe_key = self._key("probe", endpoint)
        try:
            if hasattr(self._client, "eval"):
                self._client.eval(self._RELEASE_SCRIPT, 1, probe_key, self._token)
            else:
                self._client.delete(probe_key)
            self._client.delete(self._key("circuit", endpoint))
            self._client.delete(self._key("recovery", endpoint))
        except Exception:
            self._available = False
            return

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                return

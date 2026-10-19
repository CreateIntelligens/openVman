"""Model provider settings the Admin edits, served by Backend and polled here.

Decisions and the main conversation each read their own section of the same
Backend endpoint. Both refresh at most every few seconds and keep using the
last answer they got when Backend is briefly unreachable.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from time import monotonic
from typing import Any, Final, Generic, TypeVar

import httpx

from config import get_settings

INTERNAL_PATH: Final = "/api/v1/internal/model-providers"
INTERNAL_TOKEN_HEADER: Final = "X-Internal-Token"
REFRESH_SECONDS: Final = 10.0

T = TypeVar("T")
_MISSING: Any = object()


class ModelProviderConfigUnavailable(RuntimeError):
    """Backend did not return a usable model provider document."""


def fetch_section(
    section: str,
    *,
    timeout: float,
    get: Callable[..., httpx.Response] = httpx.get,
    **request: Any,
) -> Any:
    body = fetch_document(timeout=timeout, get=get, **request)
    if section not in body:
        raise ModelProviderConfigUnavailable(f"model provider document has no {section} section")
    return body[section]


def fetch_document(
    *,
    timeout: float,
    get: Callable[..., httpx.Response] = httpx.get,
    **request: Any,
) -> dict[str, Any]:
    cfg = get_settings()
    if not cfg.gateway_internal_token or not cfg.gateway_base_url:
        raise ModelProviderConfigUnavailable("internal model provider configuration is unavailable")
    response = get(
        f"{cfg.gateway_base_url.rstrip('/')}{INTERNAL_PATH}",
        headers={INTERNAL_TOKEN_HEADER: cfg.gateway_internal_token},
        timeout=timeout,
        **request,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ModelProviderConfigUnavailable("model provider document must be an object")
    return body


class RefreshingValue(Generic[T]):
    """Reload a value at most every ``ttl`` seconds, keeping the last good one on failure."""

    def __init__(self, ttl: float = REFRESH_SECONDS) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._value: Any = _MISSING
        self._loaded_at = 0.0

    def get(
        self,
        load: Callable[[], T],
        *,
        propagate: tuple[type[BaseException], ...] = (),
        default: Any = _MISSING,
    ) -> T:
        """Return a fresh or cached value.

        ``propagate`` errors skip the cache. When nothing has loaded yet a
        failure is re-raised, unless ``default`` is given: that value is then
        cached for one interval so a down Backend is not retried on every call.
        """
        with self._lock:
            if self._value is not _MISSING and monotonic() - self._loaded_at < self.ttl:
                return self._value
        try:
            value = load()
        except propagate:
            raise
        except Exception:
            with self._lock:
                if self._value is _MISSING and default is _MISSING:
                    raise
                if self._value is _MISSING:
                    self._value = default
                self._loaded_at = monotonic()
                return self._value
        with self._lock:
            self._value = value
            self._loaded_at = monotonic()
        return value

    def clear(self) -> None:
        with self._lock:
            self._value = _MISSING
            self._loaded_at = 0.0


__all__ = [
    "INTERNAL_PATH",
    "INTERNAL_TOKEN_HEADER",
    "ModelProviderConfigUnavailable",
    "RefreshingValue",
    "fetch_document",
    "fetch_section",
]

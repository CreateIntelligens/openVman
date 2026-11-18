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
_HTTP_LOCK = threading.Lock()
_HTTP: httpx.Client | None = None


def _shared_get(*args: Any, **kwargs: Any) -> httpx.Response:
    # 每次 httpx.get 都會新建 client、重新載入 CA 憑證；設定一過期，
    # 同時進來的每一題都各讀一次，所以整個 process 共用同一個 client。
    global _HTTP
    with _HTTP_LOCK:
        if _HTTP is None:
            _HTTP = httpx.Client()
        client = _HTTP
    return client.get(*args, **kwargs)


class ModelProviderConfigUnavailable(RuntimeError):
    """Backend did not return a usable model provider document."""


def fetch_section(
    section: str,
    *,
    timeout: float,
    get: Callable[..., httpx.Response] = _shared_get,
    **request: Any,
) -> Any:
    body = fetch_document(timeout=timeout, get=get, **request)
    if section not in body:
        raise ModelProviderConfigUnavailable(f"model provider document has no {section} section")
    return body[section]


def fetch_document(
    *,
    timeout: float,
    get: Callable[..., httpx.Response] = _shared_get,
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


class _Load:
    """One in-flight load that other threads can wait on."""

    __slots__ = ("done", "error", "retry", "value")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.value: Any = _MISSING
        self.error: BaseException | None = None
        self.retry = False


class RefreshingValue(Generic[T]):
    """Reload a value at most every ``ttl`` seconds, keeping the last good one on failure.

    同時有很多執行緒要這個值時只讓一個去載入：還沒有值就等它載完；已經有舊值就
    直接回舊值，不等更新。不然 worker 剛啟動、或每次過期時，同一批題目的每個
    執行緒都各自打一次 Backend，同時 100 題時決策要多等好幾秒。
    """

    def __init__(self, ttl: float = REFRESH_SECONDS) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._loading: _Load | None = None
        self._value: Any = _MISSING
        self._loaded_at = 0.0

    def get(
        self,
        load: Callable[[], T],
        *,
        propagate: tuple[type[BaseException], ...] = (),
        default: Any = _MISSING,
        wait_timeout: float | None = None,
    ) -> T:
        """Return a fresh or cached value.

        ``propagate`` errors skip the cache. When nothing has loaded yet a
        failure is re-raised, unless ``default`` is given: that value is then
        cached for one interval so a down Backend is not retried on every call.

        Threads waiting for the same first load share its result or failure.
        ``wait_timeout`` bounds that wait; ``TimeoutError`` is raised when it
        runs out.
        """
        deadline = None if wait_timeout is None else monotonic() + max(0.0, wait_timeout)
        while True:
            with self._lock:
                stale = self._value
                if stale is not _MISSING and monotonic() - self._loaded_at < self.ttl:
                    return stale
                pending = self._loading
                owner = pending is None
                if owner:
                    pending = self._loading = _Load()
            assert pending is not None
            if owner:
                return self._run_load(pending, load, propagate, default)
            if stale is not _MISSING:
                return stale
            remaining = None if deadline is None else deadline - monotonic()
            if (remaining is not None and remaining <= 0) or not pending.done.wait(remaining):
                raise TimeoutError("timed out waiting for the value to load")
            if pending.error is not None:
                raise pending.error
            if not pending.retry:
                return pending.value
            # 載入者的錯誤是它自己的（例如它的請求被取消），等待者要自己重新載入。

    def _run_load(
        self,
        pending: _Load,
        load: Callable[[], T],
        propagate: tuple[type[BaseException], ...],
        default: Any,
    ) -> T:
        try:
            value = self._load(load, propagate, default)
        except propagate:
            pending.retry = True
            raise
        except BaseException as exc:
            pending.error = exc
            raise
        else:
            pending.value = value
            return value
        finally:
            with self._lock:
                self._loading = None
            pending.done.set()

    def _load(
        self,
        load: Callable[[], T],
        propagate: tuple[type[BaseException], ...],
        default: Any,
    ) -> T:
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

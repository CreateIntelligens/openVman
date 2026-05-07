"""Authentication middleware for public embed routes."""

from __future__ import annotations

import math
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable, Deque
from urllib.parse import urlparse

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.gateway.embed_keys import EmbedKeyRecord, EmbedKeyStore, get_embed_key_store

logger = logging.getLogger("gateway.embed.auth")

UNAUTHORIZED_BODY = {"error": "unauthorized"}
RATE_LIMIT_BODY = {"error": "rate_limited"}
PROTECTED_HTTP_PREFIXES = ("/api/embed/",)
PROTECTED_HTTP_EXACT = {"/api/embed"}
CORS_ALLOW_METHODS = "GET, POST, OPTIONS"
CORS_ALLOW_HEADERS = "Authorization, Content-Type"


@dataclass(slots=True)
class EmbedAuthContext:
    key_id: str
    tenant_id: str
    allowed_domains: list[str]
    cors_origin: str | None = None


@dataclass(slots=True)
class AuthFailure:
    status_code: int
    body: dict[str, str]
    retry_after: int | None = None
    headers: dict[str, str] = field(default_factory=dict)


class EmbedRateLimiter:
    """Sliding-window per-key rate limiter."""

    def __init__(
        self,
        *,
        limit_per_minute: int = 60,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit_per_minute
        self._time_fn = time_fn
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key_id: str) -> tuple[bool, int | None]:
        if self._limit <= 0:
            return True, None

        now = self._time_fn()
        window_start = now - 60.0
        hits = self._hits[key_id]
        while hits and hits[0] <= window_start:
            hits.popleft()

        if len(hits) >= self._limit:
            retry_after = max(1, math.ceil(60.0 - (now - hits[0])))
            return False, retry_after

        hits.append(now)
        return True, None


class EmbedAuthMiddleware:
    """ASGI middleware that protects public embed HTTP routes."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        store: EmbedKeyStore | None = None,
        rate_limiter: EmbedRateLimiter | None = None,
    ) -> None:
        self.app = app
        self.store = store or get_embed_key_store()
        self.rate_limiter = rate_limiter or EmbedRateLimiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_protected_http_path(str(scope.get("path", ""))):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        result = authenticate_embed_request(
            request,
            store=self.store,
            rate_limiter=self.rate_limiter,
        )
        if isinstance(result, AuthFailure):
            headers = dict(result.headers)
            if result.retry_after is not None:
                headers["Retry-After"] = str(result.retry_after)
            response = JSONResponse(result.body, status_code=result.status_code, headers=headers)
            await response(scope, receive, send)
            return

        if request.method == "OPTIONS":
            response = Response(status_code=204, headers=_cors_headers(result.cors_origin))
            await response(scope, receive, send)
            return

        logger.debug(
            "embed_request path=%s tenant_id=%s key_id=%s",
            scope.get("path", ""),
            result.tenant_id,
            result.key_id,
        )
        scope.setdefault("state", {})["embed_auth"] = result

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                _apply_cors_headers(MutableHeaders(scope=message), result.cors_origin)
            await send(message)

        await self.app(scope, receive, send_with_cors)


def is_protected_http_path(path: str) -> bool:
    return path in PROTECTED_HTTP_EXACT or path.startswith(PROTECTED_HTTP_PREFIXES)


def authenticate_embed_request(
    request: Request,
    *,
    store: EmbedKeyStore,
    rate_limiter: EmbedRateLimiter | None = None,
) -> EmbedAuthContext | AuthFailure:
    secret = extract_api_key(request)
    if not secret:
        return AuthFailure(status_code=401, body=UNAUTHORIZED_BODY)

    record = store.get(secret)
    if record is None:
        return AuthFailure(status_code=401, body=UNAUTHORIZED_BODY)

    if not is_origin_allowed(request, record, require_origin=False):
        return AuthFailure(status_code=403, body=UNAUTHORIZED_BODY)

    cors_origin = _allowed_cors_origin(request, record)
    if rate_limiter is not None:
        allowed, retry_after = rate_limiter.check(record.key_id)
        if not allowed:
            return AuthFailure(
                status_code=429,
                body=RATE_LIMIT_BODY,
                retry_after=retry_after,
                headers=_cors_headers(cors_origin),
            )

    return EmbedAuthContext(
        key_id=record.key_id,
        tenant_id=record.tenant_id,
        allowed_domains=list(record.allowed_domains),
        cors_origin=cors_origin,
    )


def extract_api_key(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    scheme, _, value = auth_header.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()

    query_secret = request.query_params.get("api_key") or request.query_params.get("key")
    return query_secret.strip() if query_secret else None


def is_origin_allowed(
    request: Request,
    record: EmbedKeyRecord,
    *,
    require_origin: bool,
) -> bool:
    source_host = _request_source_host(request)
    if source_host is None:
        return not require_origin

    return host_allowed(source_host, record.allowed_domains)


def _request_source_host(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin:
        return host_from_url(origin)

    referer = request.headers.get("referer")
    if referer:
        return host_from_url(referer)

    return None


def host_from_url(raw_url: str) -> str | None:
    parsed = urlparse(raw_url)
    host = parsed.hostname
    return host.lower() if host else None


def _allowed_cors_origin(request: Request, record: EmbedKeyRecord) -> str | None:
    origin = request.headers.get("origin")
    if not origin:
        return None

    source_host = host_from_url(origin)
    if source_host is None or not host_allowed(source_host, record.allowed_domains):
        return None
    return origin


def _cors_headers(origin: str | None) -> dict[str, str]:
    if origin is None:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": CORS_ALLOW_METHODS,
        "Access-Control-Allow-Headers": CORS_ALLOW_HEADERS,
        "Vary": "Origin",
    }


def _apply_cors_headers(headers: MutableHeaders, origin: str | None) -> None:
    for name, value in _cors_headers(origin).items():
        if name == "Vary" and headers.get("Vary"):
            headers["Vary"] = _vary_with_origin(headers["Vary"])
        else:
            headers[name] = value


def _vary_with_origin(value: str) -> str:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not any(part.lower() == "origin" for part in parts):
        parts.append("Origin")
    return ", ".join(parts)


def host_allowed(source_host: str, allowed_domains: list[str]) -> bool:
    for domain in allowed_domains:
        allowed = domain.lower().strip()
        if allowed == "*":
            return True
        if allowed.startswith("*.") and source_host.endswith(f".{allowed[2:]}"):
            return True
        if source_host == allowed:
            return True
    return False

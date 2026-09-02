"""Fail-closed HTTP authentication middleware with a narrow public allowlist."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .dependencies import authenticate_request
from .runtime import AuthRuntime, get_auth_runtime

_PUBLIC_EXACT_PATHS = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/auth/admin-login",
        "/api/v1/auth/admin-temporary-login",
        "/api/v1/auth/temporary-login",
        "/api/v1/health",
        "/api/v1/characters",
        "/healthz",
        "/metrics",
        "/metrics/prometheus",
        "/openapi.json",
        "/docs",
        "/redoc",
    }
)
_INTERNAL_AUTH_BYPASS_PATHS = frozenset({"/api/v1/internal/enrich"})
_PUBLIC_PREFIXES = (
    "/static/characters/",
    "/avatar-sdk/",
    "/favicon",
    "/login",
)


def is_public_path(path: str) -> bool:
    return path in _PUBLIC_EXACT_PATHS or path.startswith(_PUBLIC_PREFIXES)


def is_auth_bypass_path(path: str) -> bool:
    """Skip end-user auth for public or separately authenticated routes."""
    return path in _INTERNAL_AUTH_BYPASS_PATHS or is_public_path(path)


class FailClosedAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate every request whose path is not explicitly public."""

    def __init__(self, app, *, runtime: AuthRuntime | None = None) -> None:
        super().__init__(app)
        self._runtime = runtime

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if is_auth_bypass_path(request.url.path):
            return await call_next(request)
        try:
            authenticate_request(request, self._runtime or get_auth_runtime())
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers,
            )
        return await call_next(request)

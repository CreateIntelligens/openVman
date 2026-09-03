"""Fail-closed HTTP authentication middleware with a narrow public allowlist."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .dependencies import CurrentAccount, authenticate_request
from .embed import EMBED_KEY_HEADER, cors_headers, is_preflight_target
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
        # X-Embed-Key 一律先驗，連公開路徑也不例外：金鑰的來源白名單、
        # 額度與角色限制必須套用在它能觸及的每一條路徑上。
        runtime = self._runtime or get_auth_runtime()
        carries_embed_key = bool(request.headers.get(EMBED_KEY_HEADER, "").strip())
        origin = request.headers.get("origin", "")

        # 瀏覽器的 preflight 不會帶自訂標頭（X-Embed-Key 正是它要先問能不能帶的
        # 東西），所以這裡驗不到金鑰，只能用 Origin 對照所有啟用中的金鑰白名單。
        if (
            not carries_embed_key
            and request.method.upper() == "OPTIONS"
            and request.headers.get("access-control-request-method")
            and is_preflight_target(request.url.path)
            and _origin_allowed_by_any_key(runtime, origin)
        ):
            return Response(status_code=204, headers=cors_headers(origin))

        if not carries_embed_key and is_auth_bypass_path(request.url.path):
            return await call_next(request)

        try:
            current = authenticate_request(request, runtime)
        except HTTPException as exc:
            headers = dict(exc.headers or {})
            # 401/403/429 也要帶 CORS，否則瀏覽器會把回應整個擋掉，
            # SDK 讀不到狀態碼就無法區分金鑰失效與額度用盡。
            if carries_embed_key and _embed_error_gets_cors(runtime, request, origin):
                headers.update(cors_headers(origin))
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=headers,
            )

        if not _is_embed_principal(current):
            return await call_next(request)

        origin = request.headers.get("origin", "")
        # Preflight 不必走到 handler：允許清單與金鑰都驗過了就直接回 204。
        if request.method.upper() == "OPTIONS":
            return Response(status_code=204, headers=cors_headers(origin))

        response = await call_next(request)
        response.headers.update(cors_headers(origin))
        return response


def _is_embed_principal(current: CurrentAccount | None) -> bool:
    return current is not None and current.embed_key is not None


def _origin_allowed_by_any_key(runtime: AuthRuntime, origin: str) -> bool:
    if not origin:
        return False
    return any(
        not key.disabled and key.allows_origin(origin)
        for key in runtime.embed_keys.list_all()
    )


def _embed_error_gets_cors(runtime: AuthRuntime, request: Request, origin: str) -> bool:
    """Echo the origin on embed failures unless the origin itself was the failure.

    金鑰不存在時無從比對白名單，回應內容也只有「金鑰無效」，直接回應即可；
    金鑰存在但 Origin 不在清單上才是真的不該給 CORS。
    """
    if not origin:
        return False
    key = runtime.embed_keys.get(request.headers.get(EMBED_KEY_HEADER, "").strip())
    return key is None or key.allows_origin(origin)

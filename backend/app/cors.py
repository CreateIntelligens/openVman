"""Cross-origin access for third-party browser frontends, and a record of who uses it.

Embed key 原本就有自己的 CORS（每把 key 的網域白名單，在 auth middleware）；這裡補的是
用帳號 API key 呼叫的外部前端。兩者都在 auth middleware 裡處理：preflight 不帶金鑰，
必須在驗證之前回應，且 Embed key 允許的網域不能被這份清單擋掉。
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from app.auth.runtime import get_auth_runtime

logger = logging.getLogger("backend")

# 前端要讀得到 TTS 實際用了哪家、有沒有換備援，否則跨網域時這些 header 會被瀏覽器藏起來。
_EXPOSED_HEADERS = [
    "X-TTS-Provider",
    "X-TTS-Fallback",
    "X-TTS-Fallback-Reason",
    "X-TTS-Latency-Ms",
    "X-TTS-Cache-Hit",
]


def allowed_origins(raw: str) -> list[str]:
    return [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]


def origin_allowed(raw: str, origin: str) -> bool:
    """Whether CORS_ALLOWED_ORIGINS lets this site's browser call the API."""
    origins = allowed_origins(raw)
    origin = origin.strip().rstrip("/")
    return bool(origin) and origin != "null" and ("*" in origins or origin in origins)


def api_cors_headers(origin: str) -> dict[str, str]:
    """CORS headers for API-key callers; never a credentials flag, so cookies stay home.

    回傳請求的 Origin 而不是 *：Embed key 那套也是這樣回，兩種呼叫方的回應一致。
    """
    return {
        "Access-Control-Allow-Origin": origin.strip().rstrip("/"),
        "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Embed-Key",
        "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
        "Access-Control-Expose-Headers": ", ".join(_EXPOSED_HEADERS),
        "Access-Control-Max-Age": "600",
        "Vary": "Origin",
    }


def _is_own_site(origin: str, request: Request) -> bool:
    netloc = urlsplit(origin).netloc.lower()
    hosts = {
        request.headers.get("host", "").lower(),
        request.headers.get("x-forwarded-host", "").lower(),
    }
    return bool(netloc) and netloc in hosts


def _principal(request: Request) -> tuple[str, str, str | None]:
    current = getattr(request.state, "current_account", None)
    if current is None:
        return "anonymous", "", None
    if current.api_key is not None:
        return "api_key", current.api_key.key_id, current.user.id
    if current.embed_key is not None:
        return "embed_key", current.embed_key.key_id, current.user.id
    return "user", current.user.id, current.user.id


async def record_request_origin(request: Request, call_next):
    """Remember which external site called which credential (aggregated per pair)."""
    response = await call_next(request)
    origin = request.headers.get("origin", "").strip().rstrip("/")
    # preflight 只是瀏覽器先問能不能打，真正的請求才算一次。
    if request.method.upper() == "OPTIONS":
        return response
    if not origin or origin == "null" or _is_own_site(origin, request):
        return response
    principal_type, principal_id, user_id = _principal(request)
    try:
        await run_in_threadpool(
            get_auth_runtime().request_origins.record,
            origin=origin,
            principal_type=principal_type,
            principal_id=principal_id,
            user_id=user_id,
            path=request.url.path,
        )
    except Exception as exc:  # noqa: BLE001 - 記錄失敗不能影響請求本身
        logger.warning("request origin record failed: %s", exc)
    return response

"""Embed-key principal: route allowlist, origin check, limits, and CORS.

An embed key is a public identifier handed to a third-party page, so every
protection lives on the server: the key names exactly one project, the routes
it may reach are enumerated here, and both a per-minute sliding window and a
persisted daily counter bound how much it can spend.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock

from fastapi import HTTPException, status

from .models import AccountRole, AccountType, EmbedKeyRecord, UserRecord
from .repositories import utc_day

EMBED_KEY_HEADER = "X-Embed-Key"
EMBED_USER_ID_PREFIX = "embed:"

_STATIC_CHARACTER_PATTERN = re.compile(r"^/static/characters/(?P<char_id>[^/]+)/.+$")

# 每個項目是 (method, path)。OPTIONS preflight 由 `is_allowlisted` 另外放行，
# 因為瀏覽器送 preflight 時還沒帶上實際的方法。
_ALLOWLISTED_ROUTES = frozenset(
    {
        ("POST", "/api/v1/chat"),
        ("GET", "/api/v1/characters"),
        ("GET", "/api/v1/tts/providers"),
        ("POST", "/api/v1/tts/stream"),
        ("POST", "/v1/audio/speech"),
        ("GET", "/api/v1/health"),
    }
)
_ALLOWED_METHODS_HEADER = "GET, POST, OPTIONS"
_ALLOWED_HEADERS_HEADER = "Content-Type, X-Embed-Key"


class EmbedAuthError(HTTPException):
    """A rejection that carries the exact status the embed spec requires."""


def _unauthorized(detail: str) -> EmbedAuthError:
    return EmbedAuthError(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _forbidden(detail: str) -> EmbedAuthError:
    return EmbedAuthError(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _rate_limited(detail: str, retry_after: int) -> EmbedAuthError:
    return EmbedAuthError(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(max(1, retry_after))},
    )


def static_character_id(path: str) -> str | None:
    """Return the character id addressed by a `/static/characters/…` path."""
    match = _STATIC_CHARACTER_PATTERN.match(path)
    return match.group("char_id") if match else None


def is_allowlisted(method: str, path: str) -> bool:
    """Whether an embed principal may reach this method and path at all."""
    normalized_method = method.upper()
    if normalized_method == "OPTIONS":
        return is_preflight_target(path)
    if (normalized_method, path) in _ALLOWLISTED_ROUTES:
        return True
    return normalized_method == "GET" and static_character_id(path) is not None


def is_preflight_target(path: str) -> bool:
    """Whether an `OPTIONS` preflight names a path the allowlist covers."""
    if any(path == allowed_path for _, allowed_path in _ALLOWLISTED_ROUTES):
        return True
    return static_character_id(path) is not None


def embed_user_record(key: EmbedKeyRecord) -> UserRecord:
    """Synthesize the request-scoped principal; no such row exists in `users`."""
    return UserRecord(
        id=f"{EMBED_USER_ID_PREFIX}{key.key_id}",
        username=key.key_id,
        username_normalized=key.key_id,
        password_hash="",
        role=AccountRole.USER,
        account_type=AccountType.EMBED,
        disabled=key.disabled,
        token_version=0,
        created_at=key.created_at,
        updated_at=key.updated_at,
        created_by=key.created_by,
    )


class SlidingWindowRateLimiter:
    """Per-key request timestamps over a fixed window, held in this process."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key_id: str, limit: int, *, now: float | None = None) -> int:
        """Record a hit and return 0, or return the seconds until one frees."""
        moment = now if now is not None else time.monotonic()
        with self._lock:
            hits = self._hits[key_id]
            while hits and moment - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, int(self._window - (moment - hits[0])) + 1)
            hits.append(moment)
            return 0

    def reset(self, key_id: str | None = None) -> None:
        with self._lock:
            if key_id is None:
                self._hits.clear()
            else:
                self._hits.pop(key_id, None)


_limiter = SlidingWindowRateLimiter()


def get_rate_limiter() -> SlidingWindowRateLimiter:
    return _limiter


def cors_headers(origin: str) -> dict[str, str]:
    """The CORS headers an embed response carries; never a credentials flag."""
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Headers": _ALLOWED_HEADERS_HEADER,
        "Access-Control-Allow-Methods": _ALLOWED_METHODS_HEADER,
        "Vary": "Origin",
    }


def authorize_embed_request(
    key: EmbedKeyRecord | None,
    *,
    method: str,
    path: str,
    origin: str,
    repository,
    limiter: SlidingWindowRateLimiter | None = None,
) -> None:
    """Run every embed gate in spec order, raising the first failure."""
    if key is None or key.disabled:
        raise _unauthorized("Unknown or disabled embed key")
    if not origin or not key.allows_origin(origin):
        raise _forbidden("Origin is not allowed for this embed key")
    if not is_allowlisted(method, path):
        raise _forbidden("Route is not available to embed keys")

    character_id = static_character_id(path)
    if character_id is not None and not key.allows_character(character_id):
        raise _forbidden("Character is not allowed for this embed key")

    # Preflight 只驗身分與來源，不計入配額 — 一次真實請求會先送一個
    # OPTIONS，兩者都扣的話等於配額砍半。
    if method.upper() == "OPTIONS":
        return

    retry_after = (limiter or _limiter).check(key.key_id, key.rate_limit_per_minute)
    if retry_after:
        raise _rate_limited("Embed key rate limit exceeded", retry_after)

    repository.touch(key.key_id)
    used_today = repository.increment_daily(key.key_id)
    if used_today > key.daily_request_quota:
        raise _rate_limited(
            "Embed key daily quota exceeded",
            _seconds_until_next_utc_day(),
        )


def _seconds_until_next_utc_day() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = datetime.combine(
        (now + timedelta(days=1)).date(),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    return max(1, int((tomorrow - now).total_seconds()))


def enforce_project_binding(key: EmbedKeyRecord, supplied_project_id: str) -> None:
    """A client-supplied project that is not the key's own project is a 403."""
    candidate = supplied_project_id.strip()
    if candidate and candidate != key.project_id:
        raise _forbidden("Project is not allowed for this embed key")


__all__ = [
    "EMBED_KEY_HEADER",
    "EMBED_USER_ID_PREFIX",
    "EmbedAuthError",
    "SlidingWindowRateLimiter",
    "authorize_embed_request",
    "cors_headers",
    "embed_user_record",
    "enforce_project_binding",
    "get_rate_limiter",
    "is_allowlisted",
    "is_preflight_target",
    "static_character_id",
    "utc_day",
]

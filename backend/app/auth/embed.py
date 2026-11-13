"""Embed-key principal: route allowlist, origin check, limits, and CORS.

An embed key is a public identifier handed to a third-party page, so every
protection lives on the server: the key names exactly one project, the routes
it may reach are enumerated here, and both a per-minute sliding window and a
persisted daily counter bound how much it can spend.
"""

from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock

from fastapi import HTTPException, status

from app.project_ids import canonical_project_id

from .embed_keys_repository import utc_day
from .models import AccountRole, AccountType, EmbedKeyRecord, UserRecord

EMBED_KEY_HEADER = "X-Embed-Key"
EMBED_USER_ID_PREFIX = "embed:"

_STATIC_CHARACTER_PATTERN = re.compile(r"^/static/characters/(?P<char_id>[^/]+)/.+$")

# 每個項目是 (method, path)。OPTIONS preflight 由 `is_allowlisted` 另外放行，
# 因為瀏覽器送 preflight 時還沒帶上實際的方法。
_ALLOWLISTED_ROUTES = frozenset(
    {
        ("POST", "/api/v1/chat"),
        ("POST", "/api/v1/chat/stream"),
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


# 檢查與記錄要在 Redis 裡一次做完，兩個 process 同時檢查才不會都放行。
_REDIS_WINDOW_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', tonumber(ARGV[1]) - tonumber(ARGV[2]))
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  return tostring(oldest[2])
end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])
redis.call('EXPIRE', KEYS[1], math.ceil(tonumber(ARGV[2])) + 1)
return ''
"""


class RedisSlidingWindowRateLimiter:
    """The same per-key window shared by every Backend process through Redis."""

    def __init__(self, client, window_seconds: float = 60.0) -> None:
        self._redis = client
        self._window = window_seconds
        self._local = SlidingWindowRateLimiter(window_seconds)

    def check(self, key_id: str, limit: int, *, now: float | None = None) -> int:
        moment = now if now is not None else time.time()
        try:
            oldest = self._redis.eval(
                _REDIS_WINDOW_SCRIPT, 1, f"vman:embed-rate:{key_id}",
                moment, self._window, limit, f"{moment:.6f}:{uuid.uuid4().hex}",
            )
        except Exception:  # noqa: BLE001 - Redis 掛掉時退回這個 process 自己限流
            return self._local.check(key_id, limit, now=now)
        if isinstance(oldest, bytes):
            oldest = oldest.decode()
        if not oldest:
            return 0
        return max(1, int(self._window - (moment - float(oldest))) + 1)

    def reset(self, key_id: str | None = None) -> None:
        self._local.reset(key_id)
        try:
            if key_id is None:
                for key in self._redis.scan_iter(match="vman:embed-rate:*"):
                    self._redis.delete(key)
            else:
                self._redis.delete(f"vman:embed-rate:{key_id}")
        except Exception:  # noqa: BLE001
            pass


_limiter: SlidingWindowRateLimiter | RedisSlidingWindowRateLimiter | None = None


def get_rate_limiter() -> SlidingWindowRateLimiter | RedisSlidingWindowRateLimiter:
    global _limiter
    if _limiter is None:
        from app.config import get_tts_config

        cfg = get_tts_config()
        if getattr(cfg, "backend_workers", 1) > 1:
            import redis

            _limiter = RedisSlidingWindowRateLimiter(redis.Redis.from_url(
                cfg.redis_url, socket_timeout=0.5, socket_connect_timeout=0.5,
            ))
        else:
            _limiter = SlidingWindowRateLimiter()
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
    limiter: SlidingWindowRateLimiter | RedisSlidingWindowRateLimiter | None = None,
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

    retry_after = (limiter or get_rate_limiter()).check(key.key_id, key.rate_limit_per_minute)
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
    candidate = canonical_project_id(supplied_project_id)
    # 兩邊都換算別名：金鑰綁 "default"、呼叫端帶預設專案的正式 ID 是同一個專案。
    if candidate and candidate != canonical_project_id(key.project_id):
        raise _forbidden("Project is not allowed for this embed key")


__all__ = [
    "EMBED_KEY_HEADER",
    "EMBED_USER_ID_PREFIX",
    "EmbedAuthError",
    "RedisSlidingWindowRateLimiter",
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

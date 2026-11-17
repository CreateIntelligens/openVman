"""A2A HTTP client with exact /hub/v1 contract, rate-limiting, and local safety limits."""

from __future__ import annotations

import asyncio
from collections import deque
import copy
import inspect
import logging
import time
from typing import Any
import uuid

import httpx

from app.config import get_tts_config
from app.gateway.a2a_store import A2ACredentials, compute_key_fingerprint
from app.gateway.redis_pool import get_redis

logger = logging.getLogger("backend.gateway.a2a_client")

MAX_PAYLOAD_BYTES = 1024 * 1024  # 1 MiB
MAX_TASKS_PER_MINUTE = 60
MAX_CONCURRENCY = 4

# 檢查與記錄要在 Redis 裡一次做完，多個 process 同時送出才不會一起放行。
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


class A2ARateLimitError(RuntimeError):
    """Raised when outgoing A2A tasks exceed the per-minute sliding window."""

    def __init__(self, retry_after: int, max_calls: int = MAX_TASKS_PER_MINUTE):
        self.retry_after = max(1, int(retry_after))
        self.max_calls = max_calls
        super().__init__(
            f"A2A rate limit exceeded ({max_calls}/min); retry after {self.retry_after}s"
        )


class A2ARateLimiter:
    """Sliding-window rate limiter for outgoing Hub operations (shared via Redis when multi-process)."""

    def __init__(
        self,
        max_calls: int = MAX_TASKS_PER_MINUTE,
        window_seconds: float = 60.0,
        *,
        redis_client: Any = None,
        key: str = "default",
    ):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._redis = redis_client
        self.key = key
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    def _check_local(self, *, now: float | None = None) -> int:
        moment = now if now is not None else time.monotonic()
        while self._timestamps and self._timestamps[0] <= moment - self.window_seconds:
            self._timestamps.popleft()
        if len(self._timestamps) >= self.max_calls:
            return max(1, int(self.window_seconds - (moment - self._timestamps[0])) + 1)
        self._timestamps.append(moment)
        return 0

    async def check(self, *, now: float | None = None) -> int:
        """Record an outgoing call and return 0, or return seconds until a slot frees."""
        use_redis = (
            self._redis is not None
            or getattr(get_tts_config(), "backend_workers", 1) > 1
        )
        if use_redis:
            client = self._redis
            if client is None:
                client = await get_redis()
            if client is not None:
                moment = now if now is not None else time.time()
                try:
                    res = client.eval(
                        _REDIS_WINDOW_SCRIPT,
                        1,
                        f"vman:a2a-rate:{self.key}",
                        moment,
                        self.window_seconds,
                        self.max_calls,
                        f"{moment:.6f}:{uuid.uuid4().hex}",
                    )
                    if inspect.isawaitable(res):
                        res = await asyncio.wait_for(res, timeout=2.0)
                    if isinstance(res, bytes):
                        res = res.decode("utf-8", errors="replace")
                    if not res:
                        return 0
                    return max(1, int(self.window_seconds - (moment - float(res))) + 1)
                except Exception as exc:
                    logger.warning(
                        "Redis A2A rate limiter failed (%s); falling back to in-process limiter",
                        exc,
                    )
        async with self._lock:
            return self._check_local(now=now)

    async def acquire(self, *, skip: bool = False) -> None:
        if skip:
            return
        retry_after = await self.check()
        if retry_after > 0:
            logger.warning(
                "A2A rate limit reached (%d/min); retry after %ds",
                self.max_calls,
                retry_after,
            )
            raise A2ARateLimitError(retry_after, max_calls=self.max_calls)

    async def reset(self) -> None:
        async with self._lock:
            self._timestamps.clear()
        client = self._redis
        if client is None and getattr(get_tts_config(), "backend_workers", 1) > 1:
            client = await get_redis()
        if client is not None:
            try:
                res = client.delete(f"vman:a2a-rate:{self.key}")
                if inspect.isawaitable(res):
                    await asyncio.wait_for(res, timeout=2.0)
            except Exception:
                pass


class A2AClient:
    """HTTP client communicating strictly via legacy /hub/v1 with safety guards."""

    def __init__(
        self,
        hub_url: str = "https://a2a.david888.com",
        hub_key: str = "",
        credentials: A2ACredentials | None = None,
        timeout: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
        max_concurrency: int = MAX_CONCURRENCY,
        max_tasks_per_minute: int = MAX_TASKS_PER_MINUTE,
        max_payload_bytes: int = MAX_PAYLOAD_BYTES,
        rate_limiter: A2ARateLimiter | None = None,
    ):
        self.hub_url = hub_url.rstrip("/")
        self.hub_key = hub_key
        self.credentials = credentials
        self.timeout = timeout
        self._external_client = http_client
        self._client: httpx.AsyncClient | None = http_client
        self.max_payload_bytes = max_payload_bytes
        rate_key = compute_key_fingerprint(
            f"{self.hub_url}:{(self.hub_key or '').strip() or 'public'}"
        )
        self._rate_limiter = rate_limiter or A2ARateLimiter(
            max_calls=max_tasks_per_minute,
            key=rate_key,
        )
        self._concurrency_sem = asyncio.Semaphore(max_concurrency)
        self._skip_rate_limit = False

    def for_retry(self) -> A2AClient:
        """Return a shallow client view that skips rate-limit deduction for a single 401/403 retry."""
        clone = copy.copy(self)
        clone._skip_rate_limit = True
        return clone

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Close internal HTTP client if owned."""
        if self._client and not self._external_client:
            await self._client.aclose()
            self._client = None

    def _auth_headers(self) -> dict[str, str]:
        """Headers required for authenticated agent operations (issued-agent token only)."""
        if not self.credentials:
            raise RuntimeError("Agent credentials missing; registration required")
        return {
            "X-Agent-ID": self.credentials.agent_id,
            "Authorization": f"Bearer {self.credentials.agent_token}",
            "Content-Type": "application/json",
        }

    async def get_status(self) -> dict[str, Any]:
        """Query Hub status, mode, and capability card."""
        client = await self._get_client()
        resp = await client.get(f"{self.hub_url}/hub/v1/status")
        resp.raise_for_status()
        return resp.json()

    async def register(
        self,
        display_name: str = "openVman",
        idempotency_key: str | None = None,
        capabilities: list[str] | None = None,
        fingerprint_key: str = "",
    ) -> A2ACredentials:
        """Register agent with Hub; X-Hub-Key is sent ONLY here."""
        client = await self._get_client()
        headers: dict[str, str] = {"Content-Type": "application/json"}
        clean_key = self.hub_key.strip() if self.hub_key else ""
        if clean_key:
            headers["X-Hub-Key"] = clean_key

        payload = {
            "displayName": display_name,
            "providerFamily": "openvman",
            "transportId": "http-json",
            "capabilities": capabilities or ["text/plain"],
            "registrationIdempotencyKey": idempotency_key or f"openvman-{uuid.uuid4().hex[:12]}",
        }

        url = f"{self.hub_url}/hub/v1/agents/register"
        logger.info("Registering agent with A2A Hub at %s (display_name=%s)", url, display_name)
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        identity = data.get("identity", data)
        creds = A2ACredentials(
            agentId=identity["agentId"],
            agentToken=identity["agentToken"],
            circleId=identity.get("circleId", "public"),
            hubUrl=self.hub_url,
            hubKeyFingerprint=compute_key_fingerprint(clean_key, fingerprint_key),
            displayName=display_name,
            expiresAt=identity.get("expiresAt", ""),
        )
        self.credentials = creds
        logger.info(
            "Registered successfully as agent %s in circle %s",
            creds.agent_id,
            creds.circle_id,
        )
        return creds

    async def acknowledge_task(self, sequence: int) -> bool:
        """Send instant acknowledgment for a received sequence."""
        if not self.credentials:
            return False
        client = await self._get_client()
        url = f"{self.hub_url}/hub/v1/agents/{self.credentials.agent_id}/inbox/{sequence}/ack"
        try:
            resp = await client.post(url, headers=self._auth_headers(), timeout=3.0)
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.warning("Failed to ACK sequence %d: %s", sequence, e)
            return False

    async def send_task(
        self,
        target_agent_id: str,
        message: str,
        context_id: str | None = None,
        task_id: str | None = None,
        idempotency_key: str | None = None,
        *,
        skip_rate_limit: bool = False,
    ) -> dict[str, Any]:
        """Dispatch a task message with payload validation and rate limiting."""
        encoded_len = len(message.encode("utf-8"))
        if encoded_len > self.max_payload_bytes:
            raise ValueError(f"Payload size {encoded_len} bytes exceeds maximum limit {self.max_payload_bytes} bytes")

        headers = self._auth_headers()
        await self._rate_limiter.acquire(skip=skip_rate_limit or self._skip_rate_limit)
        async with self._concurrency_sem:
            client = await self._get_client()
            url = f"{self.hub_url}/hub/v1/agents/{target_agent_id}/tasks"
            payload = {
                "taskId": task_id or str(uuid.uuid4()),
                "contextId": context_id or f"ctx-{uuid.uuid4().hex[:8]}",
                "idempotencyKey": idempotency_key or str(uuid.uuid4()),
                "message": message,
            }
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def list_peers(self, state: str | None = None) -> list[dict[str, Any]]:
        """List discoverable peers in the same private circle."""
        headers = self._auth_headers()
        client = await self._get_client()
        url = f"{self.hub_url}/hub/v1/agents"
        params = {}
        if state and state != "all":
            params["state"] = state
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data.get("agents", data) if isinstance(data, dict) else data

    async def broadcast_group(
        self,
        group_id: str,
        message: str,
        *,
        skip_rate_limit: bool = False,
    ) -> dict[str, Any]:
        """Broadcast a message to an active group with size check."""
        encoded_len = len(message.encode("utf-8"))
        if encoded_len > self.max_payload_bytes:
            raise ValueError(f"Payload size {encoded_len} exceeds maximum limit {MAX_PAYLOAD_BYTES}")

        headers = self._auth_headers()
        await self._rate_limiter.acquire(skip=skip_rate_limit or self._skip_rate_limit)
        async with self._concurrency_sem:
            client = await self._get_client()
            url = f"{self.hub_url}/hub/v1/groups/{group_id}/messages"
            payload = {"message": message}
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

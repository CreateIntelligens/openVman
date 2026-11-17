"""A2A inbound bridge daemon composing lease management, inbox workers, and outbound reply delivery."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any
import uuid

import httpx

from app.config import TTSRouterConfig, get_tts_config
from app.gateway.a2a_bridge_inbox import A2ABridgeInboxMixin
from app.gateway.a2a_bridge_lease import (
    A2ABridgeLeaseMixin,
    _RELEASE_LEASE_SCRIPT,
    _RENEW_LEASE_SCRIPT,
    _redis_text,
)
from app.gateway.a2a_bridge_outbound import (
    A2ABridgeOutboundMixin,
    A2ACredentialsUnavailableError,
    _NO_REPLY_TOKEN,
    _parse_retry_after_seconds,
)
from app.gateway.a2a_client import A2AClient
from app.gateway.a2a_queue import A2AWorkQueue
from app.gateway.a2a_store import A2ACredentialStore, compute_key_fingerprint
from app.gateway.redis_pool import get_redis

logger = logging.getLogger("backend.gateway.a2a_bridge")

__all__ = [
    "A2ABridgeDaemon",
    "A2ACredentialsUnavailableError",
    "_NO_REPLY_TOKEN",
    "_RELEASE_LEASE_SCRIPT",
    "_RENEW_LEASE_SCRIPT",
    "_parse_retry_after_seconds",
    "_redis_text",
    "get_a2a_bridge_daemon",
]


class A2ABridgeDaemon(
    A2ABridgeLeaseMixin,
    A2ABridgeOutboundMixin,
    A2ABridgeInboxMixin,
):
    """Singleton bridge daemon managing leader election, durable queue, and SSE streaming."""

    def __init__(
        self,
        config: TTSRouterConfig | None = None,
        store: A2ACredentialStore | None = None,
        queue: A2AWorkQueue | None = None,
        client: A2AClient | None = None,
    ):
        self.config = config or get_tts_config()
        self.store = store or A2ACredentialStore(
            self.config.a2a_credentials_path,
            encryption_key=self.config.a2a_credentials_encryption_key or self.config.session_jwt_secret,
        )
        self.queue = queue or A2AWorkQueue(self.config.a2a_queue_db_path)
        self.client = client
        self.worker_id = f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"

        self._running = False
        self._is_leader = False
        self._main_task: asyncio.Task[None] | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._ack_task: asyncio.Task[None] | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._last_queue_prune = 0.0
        self._has_injected_client = client is not None
        self._creds_stat: tuple[int, int, int] | None = self._file_stat_key() if client is not None else None
        self._inflight_acks: set[int] = set()
        self._processing_tasks: set[asyncio.Task[Any]] = set()
        self._inflight_replies: set[asyncio.Task[Any]] = set()
        self._inflight_ack_tasks: set[asyncio.Task[Any]] = set()
        self._active_event_ids: set[int] = set()
        self._last_orphan_sweep: float = self._monotonic()
        self._orphan_sweep_interval_seconds: float = max(
            0.5,
            float(os.environ.get("A2A_ORPHAN_SWEEP_INTERVAL_SECONDS", "30.0")),
        )
        self._pending_requeue: bool = False
        self._lease_expires_at: float = 0.0
        self._lease_grace_active: bool = False
        self._brain_timeout_seconds: float = float(self.config.a2a_brain_timeout_seconds)

    async def _get_redis(self) -> Any:
        return await get_redis()

    def _monotonic(self) -> float:
        return time.monotonic()

    @property
    def is_running(self) -> bool:
        return self._running and self._main_task is not None and not self._main_task.done()

    def _hub_scope(self) -> str:
        encryption_key = (
            self.config.a2a_credentials_encryption_key
            or self.config.session_jwt_secret
        )
        circle_fingerprint = compute_key_fingerprint(
            self.config.a2a_hub_key or "public",
            encryption_key,
        )
        return compute_key_fingerprint(
            f"{self.config.a2a_hub_url}:{circle_fingerprint}",
            encryption_key,
        )

    def start(self) -> None:
        """Start daemon background tasks if enabled."""
        if not self.config.a2a_enabled:
            logger.info("A2A Bridge is disabled (A2A_ENABLED=false); skipping startup")
            return
        if self._running:
            return
        self.queue.reset_shutdown()
        self._running = True
        self._main_task = asyncio.create_task(self._leader_lifecycle_loop(), name="a2a-bridge-leader")
        self._worker_task = asyncio.create_task(self._queue_worker_loop(), name="a2a-queue-worker")
        self._ack_task = asyncio.create_task(self._ack_worker_loop(), name="a2a-ack-worker")
        logger.info("A2A Bridge daemon started (worker_id=%s)", self.worker_id)

    def _cancel_processing_tasks(self, *, cancel_inflight_replies: bool = False) -> list[asyncio.Task[Any]]:
        """Cancel active queue worker tasks (and optionally in-flight outbound reply tasks)."""
        tasks = [t for t in self._processing_tasks if not t.done()]
        if cancel_inflight_replies:
            tasks.extend(t for t in self._inflight_replies if not t.done())
        for task in tasks:
            task.cancel()
        return tasks

    async def stop(self) -> None:
        """Gracefully wait for shielded outbound dispatches, release leadership, and stop tasks within 8s."""
        stop_deadline = self._monotonic() + 6.5
        self._running = False
        self._is_leader = False
        self._lease_expires_at = 0.0
        self._lease_grace_active = False
        self.queue.begin_shutdown(busy_timeout_ms=250)

        proc_tasks = self._cancel_processing_tasks(cancel_inflight_replies=False)
        tasks = [t for t in (self._main_task, self._worker_task, self._ack_task) if t and not t.done()]
        for t in tasks:
            t.cancel()
        all_tasks = [*tasks, *proc_tasks]
        if all_tasks:
            remaining = max(0.2, stop_deadline - self._monotonic())
            try:
                await asyncio.wait_for(
                    asyncio.gather(*all_tasks, return_exceptions=True),
                    timeout=min(2.0, remaining),
                )
            except Exception:
                pass

        inflight = [t for t in (*self._inflight_replies, *self._inflight_ack_tasks) if not t.done()]
        if inflight:
            remaining = max(0.2, stop_deadline - self._monotonic())
            try:
                await asyncio.wait_for(
                    asyncio.gather(*inflight, return_exceptions=True),
                    timeout=min(3.5, remaining),
                )
            except Exception:
                for t in inflight:
                    if not t.done():
                        t.cancel()
                remaining_cancel = max(0.1, stop_deadline - self._monotonic())
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*inflight, return_exceptions=True),
                        timeout=min(0.5, remaining_cancel),
                    )
                except Exception:
                    pass

        remaining = max(0.2, stop_deadline - self._monotonic())
        try:
            await asyncio.wait_for(self._release_leader_lease(), timeout=min(1.0, remaining))
        except Exception:
            pass

        if self.client:
            await self.client.close()
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
        logger.info("A2A Bridge daemon stopped")


# Module-level singleton instance for FastAPI lifespan
_bridge_daemon: A2ABridgeDaemon | None = None


def get_a2a_bridge_daemon() -> A2ABridgeDaemon:
    global _bridge_daemon
    if _bridge_daemon is None:
        _bridge_daemon = A2ABridgeDaemon()
    return _bridge_daemon

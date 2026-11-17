"""Redis leader lease election, renewal, and abdication lifecycle for A2ABridgeDaemon."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from app.gateway.a2a_store import compute_key_fingerprint

logger = logging.getLogger("backend.gateway.a2a_bridge")

_RENEW_LEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_LEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


def _redis_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class A2ABridgeLeaseMixin:
    """Mixin encapsulating Redis leader election, lease renewal, and orphan requeue orchestration."""

    @property
    def is_leader(self) -> bool:
        if not self._is_leader:
            return False
        if self._lease_expires_at > 0.0 and not self._allow_standalone_leader_fallback():
            return self._monotonic() < self._lease_expires_at
        return True

    def _allow_standalone_leader_fallback(self) -> bool:
        """Only single-process dev mode may assume leadership without Redis."""
        return bool(self.config.is_dev and getattr(self.config, "backend_workers", 1) <= 1)

    def _lease_safety_margin(self) -> float:
        ttl = float(max(2, self.config.a2a_leader_lease_ttl_seconds))
        return min(1.5, max(0.5, ttl * 0.2))

    def _has_valid_local_lease(self) -> bool:
        return (self._monotonic() + self._lease_safety_margin()) < self._lease_expires_at

    def _record_lease_deadline(self, started_at: float) -> None:
        self._lease_expires_at = started_at + float(self.config.a2a_leader_lease_ttl_seconds)
        self._lease_grace_active = False

    async def _acquire_leader_lease(self) -> bool:
        """Try to acquire Redis leader lease for this hub instance."""
        try:
            r = await self._get_redis()
            if r is None:
                raise ConnectionError("Redis unavailable")
            scope = self._hub_scope()
            lease_key = f"a2a:leader:lease:{compute_key_fingerprint(scope)}"
            op_started = self._monotonic()
            acquired = await asyncio.wait_for(
                r.set(
                    lease_key,
                    self.worker_id,
                    nx=True,
                    ex=self.config.a2a_leader_lease_ttl_seconds,
                ),
                timeout=2.0,
            )
            if acquired:
                self._record_lease_deadline(op_started)
                return True
            current_owner = await asyncio.wait_for(r.get(lease_key), timeout=2.0)
            if _redis_text(current_owner) == self.worker_id:
                op_started = self._monotonic()
                renewed = await asyncio.wait_for(
                    r.eval(
                        _RENEW_LEASE_SCRIPT,
                        1,
                        lease_key,
                        self.worker_id,
                        self.config.a2a_leader_lease_ttl_seconds,
                    ),
                    timeout=2.0,
                )
                if renewed:
                    self._record_lease_deadline(op_started)
                    return True
            self._lease_expires_at = 0.0
            self._lease_grace_active = False
            return False
        except Exception as exc:
            # Multi-process mode must remain conservative so no two processes become leader.
            if self._allow_standalone_leader_fallback():
                logger.debug("Redis unavailable in dev single-process mode; assuming standalone leader: %s", exc)
                return True
            self._lease_expires_at = 0.0
            self._lease_grace_active = False
            logger.warning("Failed to contact Redis for A2A leader lease: %s", exc)
            return False

    def _run_pending_requeue(self, reason: str = "leader transition") -> bool:
        """Recover orphaned PROCESSING rows while preserving this worker's active tasks; retry on DB failure."""
        try:
            recovered = self.queue.requeue_processing_events(
                self._hub_scope(),
                exclude_worker_id=self.worker_id,
                exclude_active_event_ids=set(self._active_event_ids),
            )
            if recovered:
                logger.info("Recovered %d interrupted A2A processing event(s) on %s", recovered, reason)
            self._pending_requeue = False
            return True
        except Exception as exc:
            self._pending_requeue = True
            logger.warning("Deferred A2A requeue_processing_events on %s (%s); will retry", reason, exc)
            return False

    async def _renew_leader_lease(self) -> bool:
        """Renew current leader lease in Redis, retaining leadership until local lease expiry on transient timeouts."""
        try:
            r = await self._get_redis()
            if r is None:
                raise ConnectionError("Redis unavailable")
            scope = self._hub_scope()
            lease_key = f"a2a:leader:lease:{compute_key_fingerprint(scope)}"
            redis_timeout = 2.0
            if self._lease_expires_at > 0.0:
                grace_left = self._lease_expires_at - self._lease_safety_margin() - self._monotonic()
                redis_timeout = min(2.0, max(0.25, grace_left))
            op_started = self._monotonic()
            renewed = await asyncio.wait_for(
                r.eval(
                    _RENEW_LEASE_SCRIPT,
                    1,
                    lease_key,
                    self.worker_id,
                    self.config.a2a_leader_lease_ttl_seconds,
                ),
                timeout=redis_timeout,
            )
            if renewed:
                self._record_lease_deadline(op_started)
                if self._pending_requeue:
                    self._run_pending_requeue(reason="pending requeue retry")
                return True
            reacquire_started = self._monotonic()
            reacquired = await asyncio.wait_for(
                r.set(
                    lease_key,
                    self.worker_id,
                    nx=True,
                    ex=self.config.a2a_leader_lease_ttl_seconds,
                ),
                timeout=2.0,
            )
            if reacquired:
                self._record_lease_deadline(reacquire_started)
                self._is_leader = True
                self._pending_requeue = True
                self._run_pending_requeue(reason="lease re-acquisition")
                return True
            self._is_leader = False
            self._lease_expires_at = 0.0
            self._lease_grace_active = False
            return False
        except Exception as exc:
            if self._allow_standalone_leader_fallback():
                return True
            if self._has_valid_local_lease():
                self._lease_grace_active = True
                logger.warning(
                    "Failed to renew Redis A2A leader lease (%s); retaining leadership for %.2fs before local expiry",
                    exc,
                    max(0.0, self._lease_expires_at - self._lease_safety_margin() - self._monotonic()),
                )
                return True
            self._is_leader = False
            self._lease_expires_at = 0.0
            self._lease_grace_active = False
            logger.warning("Failed to renew Redis A2A leader lease: %s", exc)
            return False

    async def _release_leader_lease(self) -> None:
        """Release Redis lease on shutdown."""
        self._lease_expires_at = 0.0
        self._lease_grace_active = False
        try:
            r = await self._get_redis()
            if r is None:
                return
            scope = self._hub_scope()
            lease_key = f"a2a:leader:lease:{compute_key_fingerprint(scope)}"
            await asyncio.wait_for(
                r.eval(_RELEASE_LEASE_SCRIPT, 1, lease_key, self.worker_id),
                timeout=1.5,
            )
        except Exception:
            pass

    async def _leader_lifecycle_loop(self) -> None:
        """Manages leader election and runs SSE stream only when leader."""
        while self._running:
            try:
                has_lease = await self._acquire_leader_lease()
                if has_lease:
                    if not self._is_leader:
                        logger.info("A2A Bridge worker %s acquired leader lease", self.worker_id)
                        self._pending_requeue = True
                        self._run_pending_requeue(reason="leader acquisition")
                        self._is_leader = True

                    # Run SSE stream with periodic lease renewal
                    stream_task = asyncio.create_task(self._run_sse_stream())
                    renew_interval = max(0.8, min(self.config.a2a_leader_lease_ttl_seconds / 4.0, 3.0))

                    while self._running and self.is_leader and not stream_task.done():
                        sleep_for = renew_interval
                        if self._lease_expires_at > 0.0 and not self._allow_standalone_leader_fallback():
                            grace_left = self._lease_expires_at - self._lease_safety_margin() - self._monotonic()
                            if self._lease_grace_active or grace_left < renew_interval:
                                sleep_for = max(0.1, min(renew_interval, grace_left * 0.4 if grace_left > 0.0 else 0.1))
                        await asyncio.sleep(sleep_for)
                        still_leader = await self._renew_leader_lease()
                        if not still_leader:
                            logger.warning("A2A Bridge worker %s lost leader lease; abdicating", self.worker_id)
                            self._is_leader = False
                            stream_task.cancel()
                            cancelled = self._cancel_processing_tasks(cancel_inflight_replies=True)
                            if cancelled:
                                try:
                                    await asyncio.wait_for(
                                        asyncio.gather(*cancelled, return_exceptions=True),
                                        timeout=2.0,
                                    )
                                except Exception:
                                    pass
                            break

                    if stream_task and not stream_task.done():
                        stream_task.cancel()
                        try:
                            await stream_task
                        except asyncio.CancelledError:
                            pass
                    if self._running and self._is_leader and not self.is_leader:
                        still_leader = await self._renew_leader_lease()
                        if not still_leader:
                            self._is_leader = False
                            cancelled = self._cancel_processing_tasks(cancel_inflight_replies=True)
                            if cancelled:
                                try:
                                    await asyncio.wait_for(
                                        asyncio.gather(*cancelled, return_exceptions=True),
                                        timeout=2.0,
                                    )
                                except Exception:
                                    pass
                else:
                    if self._is_leader:
                        self._is_leader = False
                        cancelled = self._cancel_processing_tasks(cancel_inflight_replies=True)
                        if cancelled:
                            try:
                                await asyncio.wait_for(
                                    asyncio.gather(*cancelled, return_exceptions=True),
                                    timeout=2.0,
                                )
                            except Exception:
                                pass
                    # Standby wait before re-checking lease; keep short relative to lease TTL for timely failover.
                    ttl = self.config.a2a_leader_lease_ttl_seconds
                    standby_delay = min(0.5, max(0.15, ttl / 12.0)) + random.uniform(0.02, 0.1)
                    await asyncio.sleep(standby_delay)
            except asyncio.CancelledError:
                self._is_leader = False
                self._cancel_processing_tasks(cancel_inflight_replies=False)
                break
            except Exception as exc:
                if self._is_leader:
                    self._is_leader = False
                    cancelled = self._cancel_processing_tasks(cancel_inflight_replies=True)
                    if cancelled:
                        try:
                            await asyncio.wait_for(
                                asyncio.gather(*cancelled, return_exceptions=True),
                                timeout=2.0,
                            )
                        except Exception:
                            pass
                logger.warning("A2A leader loop error: %s; retrying...", exc)
                await asyncio.sleep(1.0)

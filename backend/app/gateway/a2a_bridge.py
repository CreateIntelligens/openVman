"""A2A inbound bridge daemon with SQLite WAL work queue, Redis leader lease, and anti-echo routing."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any
import uuid

import httpx

from app.config import TTSRouterConfig, get_tts_config
from app.gateway.a2a_client import A2AClient
from app.gateway.a2a_queue import A2AWorkQueue
from app.gateway.a2a_store import A2ACredentialStore, A2ACredentials, compute_key_fingerprint
from app.gateway.redis_pool import get_redis

logger = logging.getLogger("backend.gateway.a2a_bridge")

_NO_REPLY_TOKEN = "[[A2A_NO_REPLY]]"
_A2A_REPLY_QUESTION = {
    "type": "choice",
    "instructions": "這是另一個 AI 代理傳來的訊息。我方是否需要回覆？",
    "criteria": {
        "reply": "含有問題、請求、需要確認或需要我方採取行動",
        "no_reply": "只是確認收到、道謝、結束對話或單純告知已完成",
    },
}
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


class A2ABridgeDaemon:
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
        self.worker_id = f"worker-{uuid.uuid4().hex[:8]}"

        self._running = False
        self._is_leader = False
        self._main_task: asyncio.Task[None] | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._ack_task: asyncio.Task[None] | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._last_queue_prune = 0.0

    @property
    def is_running(self) -> bool:
        return self._running and self._main_task is not None and not self._main_task.done()

    @property
    def is_leader(self) -> bool:
        return self._is_leader

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
        self._running = True
        self._main_task = asyncio.create_task(self._leader_lifecycle_loop(), name="a2a-bridge-leader")
        self._worker_task = asyncio.create_task(self._queue_worker_loop(), name="a2a-queue-worker")
        self._ack_task = asyncio.create_task(self._ack_worker_loop(), name="a2a-ack-worker")
        logger.info("A2A Bridge daemon started (worker_id=%s)", self.worker_id)

    async def stop(self) -> None:
        """Gracefully release leadership and stop background tasks."""
        self._running = False
        self._is_leader = False

        tasks = [t for t in (self._main_task, self._worker_task, self._ack_task) if t and not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5.0)
            except Exception:
                pass

        await self._release_leader_lease()

        if self.client:
            await self.client.close()
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
        logger.info("A2A Bridge daemon stopped")

    async def _acquire_leader_lease(self) -> bool:
        """Try to acquire Redis leader lease for this hub instance."""
        try:
            r = await get_redis()
            scope = self._hub_scope()
            lease_key = f"a2a:leader:lease:{compute_key_fingerprint(scope)}"
            acquired = await r.set(
                lease_key,
                self.worker_id,
                nx=True,
                ex=self.config.a2a_leader_lease_ttl_seconds,
            )
            if acquired:
                return True
            current_owner = await r.get(lease_key)
            if _redis_text(current_owner) == self.worker_id:
                renewed = await r.eval(
                    _RENEW_LEASE_SCRIPT,
                    1,
                    lease_key,
                    self.worker_id,
                    self.config.a2a_leader_lease_ttl_seconds,
                )
                return bool(renewed)
            return False
        except Exception as exc:
            # If Redis is unreachable in dev mode, permit local leader
            if self.config.is_dev:
                logger.debug("Redis unavailable in dev mode; assuming standalone leader: %s", exc)
                return True
            logger.warning("Failed to contact Redis for A2A leader lease: %s", exc)
            return False

    async def _renew_leader_lease(self) -> bool:
        """Renew current leader lease in Redis."""
        try:
            r = await get_redis()
            scope = self._hub_scope()
            lease_key = f"a2a:leader:lease:{compute_key_fingerprint(scope)}"
            renewed = await r.eval(
                _RENEW_LEASE_SCRIPT,
                1,
                lease_key,
                self.worker_id,
                self.config.a2a_leader_lease_ttl_seconds,
            )
            return bool(renewed)
        except Exception:
            if self.config.is_dev:
                return True
            return False

    async def _release_leader_lease(self) -> None:
        """Release Redis lease on shutdown."""
        try:
            r = await get_redis()
            scope = self._hub_scope()
            lease_key = f"a2a:leader:lease:{compute_key_fingerprint(scope)}"
            await r.eval(_RELEASE_LEASE_SCRIPT, 1, lease_key, self.worker_id)
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
                        self._is_leader = True

                    # Run SSE stream with periodic lease renewal
                    stream_task = asyncio.create_task(self._run_sse_stream())
                    renew_interval = max(self.config.a2a_leader_lease_ttl_seconds // 3, 2)

                    while self._running and self._is_leader and not stream_task.done():
                        await asyncio.sleep(renew_interval)
                        still_leader = await self._renew_leader_lease()
                        if not still_leader:
                            logger.warning("A2A Bridge worker %s lost leader lease; abdicating", self.worker_id)
                            self._is_leader = False
                            stream_task.cancel()
                            break

                    if stream_task and not stream_task.done():
                        stream_task.cancel()
                        try:
                            await stream_task
                        except asyncio.CancelledError:
                            pass
                else:
                    if self._is_leader:
                        self._is_leader = False
                    # Standby wait before re-checking lease
                    await asyncio.sleep(5.0 + random.uniform(0.5, 2.0))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("A2A leader loop error: %s; retrying...", exc)
                await asyncio.sleep(3.0)

    async def _ensure_credentials(self) -> A2ACredentials:
        """Load from encrypted store or register freshly with Hub."""
        if not self.config.gateway_internal_token:
            raise RuntimeError("A2A requires GATEWAY_INTERNAL_TOKEN for Brain forwarding")
        if not self.config.a2a_hub_key and not self.config.a2a_allow_public_circle:
            raise RuntimeError("A2A private-circle key is not configured")
        if not self.config.a2a_credentials_encryption_key and not self.config.session_jwt_secret:
            raise RuntimeError("A2A credential encryption key is not configured")
        creds = self.store.load(
            expected_hub_url=self.config.a2a_hub_url,
            current_hub_key=self.config.a2a_hub_key,
        )
        if creds:
            if not self.client:
                self.client = A2AClient(
                    hub_url=self.config.a2a_hub_url,
                    hub_key=self.config.a2a_hub_key,
                    credentials=creds,
                    max_concurrency=self.config.a2a_max_concurrency,
                    max_tasks_per_minute=self.config.a2a_max_tasks_per_minute,
                )
            else:
                self.client.credentials = creds
            return creds

        if not self.client:
            self.client = A2AClient(
                hub_url=self.config.a2a_hub_url,
                hub_key=self.config.a2a_hub_key,
                max_concurrency=self.config.a2a_max_concurrency,
                max_tasks_per_minute=self.config.a2a_max_tasks_per_minute,
            )
        creds = await self.client.register(
            display_name=self.config.a2a_display_name,
            idempotency_key=f"openvman-registration-{self._hub_scope()[:24]}",
            fingerprint_key=self.config.a2a_credentials_encryption_key or self.config.session_jwt_secret,
        )
        self.store.save(creds)
        return creds

    async def _run_sse_stream(self) -> None:
        """Connect to SSE endpoint and stream inbound events with exponential full-jitter reconnect."""
        backoff = 1.0
        while self._running and self._is_leader:
            try:
                creds = await self._ensure_credentials()
                backoff = 1.0  # Reset backoff on successful connect
                await self._stream_inbox(creds)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._running or not self._is_leader:
                    break
                jitter = random.uniform(0.5, 1.5)
                delay = min(backoff * jitter, 30.0)
                logger.warning("A2A SSE stream interrupted: %s; reconnecting in %.1fs", exc, delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2.0, 30.0)

    async def _stream_inbox(self, creds: A2ACredentials) -> None:
        """Open persistent SSE stream and commit events before ACK."""
        if not self._http_client or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0))

        hub_scope = self._hub_scope()
        last_seq = self.queue.get_last_processed_sequence(hub_scope)

        url = f"{self.config.a2a_hub_url.rstrip('/')}/hub/v1/agents/{creds.agent_id}/inbox/stream"
        params = {}
        if last_seq > 0:
            params["afterSequence"] = str(last_seq)

        headers = {
            "Accept": "text/event-stream",
            "X-Agent-ID": creds.agent_id,
            "Authorization": f"Bearer {creds.agent_token}",
        }
        if last_seq > 0:
            headers["Last-Event-ID"] = str(last_seq)

        async with self._http_client.stream("GET", url, params=params, headers=headers) as response:
            if response.status_code in (401, 403, 404):
                logger.warning("Hub rejected agent credentials (%d); invalidating store", response.status_code)
                self.store.clear()
                raise RuntimeError(f"Authentication rejected: {response.status_code}")
            response.raise_for_status()

            current_event = "message"
            async for raw_line in response.aiter_lines():
                if not self._running or not self._is_leader:
                    break
                line = raw_line.strip()
                if not line or line.startswith(":"):
                    continue

                if line.startswith("event:"):
                    current_event = line[len("event:"):].strip()
                    continue

                if line.startswith("data:"):
                    data_str = line[len("data:"):].strip()
                    if current_event in ("task", "message"):
                        try:
                            payload = json.loads(data_str)
                            await self._on_raw_task_received(hub_scope, payload)
                        except Exception as exc:
                            logger.warning("Invalid JSON in SSE data: %s (%r)", exc, data_str)
                    current_event = "message"

    async def _on_raw_task_received(self, hub_scope: str, task: dict[str, Any]) -> None:
        """DURABLE ENQUEUE BEFORE ACK: Commit to SQLite WAL first, then dispatch ACK."""
        sequence = task.get("sequence")
        task_id = str(task.get("taskId") or f"task-{uuid.uuid4().hex[:8]}")
        requester = str(task.get("requesterAgentId") or task.get("fromAgentId") or "")
        message = str(task.get("message") or "")
        context_id = task.get("contextId")
        group_id = task.get("groupId")

        if sequence is None or not isinstance(sequence, int):
            return

        # 1. Atomic durable enqueue
        inserted = self.queue.enqueue_event(
            hub_scope=hub_scope,
            sequence=sequence,
            task_id=task_id,
            requester_agent_id=requester,
            message=message,
            context_id=context_id,
            group_id=group_id,
        )
        if not inserted:
            return

        # 2. Instant ACK dispatch
        if self.client:
            ack_ok = await self.client.acknowledge_task(sequence)
            if ack_ok:
                self.queue.mark_ack_dispatched(hub_scope, sequence)
            else:
                self.queue.record_ack_failure(hub_scope, sequence)

    async def _ack_worker_loop(self) -> None:
        """Retry durable ACKs only while this process owns the bridge lease."""
        hub_scope = self._hub_scope()
        while self._running:
            try:
                if not self._is_leader or not self.client:
                    await asyncio.sleep(0.5)
                    continue
                pending = self.queue.get_pending_ack_events(hub_scope, limit=20)
                if not pending:
                    await asyncio.sleep(0.5)
                    continue
                for event in pending:
                    sequence = int(event["sequence"])
                    if await self.client.acknowledge_task(sequence):
                        self.queue.mark_ack_dispatched(hub_scope, sequence)
                    else:
                        self.queue.record_ack_failure(hub_scope, sequence, retry_after_seconds=2.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("A2A ACK worker loop error: %s", exc)
                await asyncio.sleep(1.0)

    async def _queue_worker_loop(self) -> None:
        """Background worker loop draining unprocessed events from SQLite."""
        hub_scope = self._hub_scope()
        sem = asyncio.Semaphore(self.config.a2a_max_concurrency)

        while self._running:
            try:
                if not self._is_leader:
                    await asyncio.sleep(0.5)
                    continue
                if time.monotonic() - self._last_queue_prune > 300:
                    self.queue.prune_terminal_events(self.config.a2a_queue_retention_days)
                    self._last_queue_prune = time.monotonic()
                events = self.queue.get_unprocessed_events(hub_scope, limit=self.config.a2a_max_concurrency)
                if not events:
                    await asyncio.sleep(0.5)
                    continue

                async def _process_single(event: dict[str, Any]) -> None:
                    async with sem:
                        await self._process_queued_event(event)

                await asyncio.gather(*(_process_single(ev) for ev in events), return_exceptions=True)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Queue worker loop error: %s", exc)
                await asyncio.sleep(1.0)

    async def _process_queued_event(self, event: dict[str, Any]) -> None:
        """Process one event: Anti-Echo check -> Brain chat -> Reply send."""
        event_id = event["id"]
        message = event["message"]
        requester_id = event["requester_agent_id"]
        context_id = event.get("context_id")
        task_id = event["task_id"]

        self.queue.record_processing_start(event_id)

        # 0. Optional: skip the whole Brain turn when Jev is near-certain the
        # peer only acknowledged or closed. Anything less goes to Brain.
        if await self._jev_says_no_reply(message):
            logger.info("Jev pre-filter: no reply needed for event %d", event_id)
            self.queue.record_suppressed(event_id, "jev")
            return

        # 1. Forward peer content to Brain; Brain decides suppression.
        reply = await self._query_brain(
            message,
            requester_id=requester_id,
            task_id=task_id,
            context_id=context_id,
        )
        if not reply:
            self.queue.record_failed(event_id, "Brain returned empty reply")
            return

        # 3. Exact [[A2A_NO_REPLY]] token suppression
        if _NO_REPLY_TOKEN in reply:
            logger.info("Brain returned [[A2A_NO_REPLY]] for event %d; dialogue ended", event_id)
            self.queue.record_suppressed(event_id, "token")
            return

        # 4. Outbound reply dispatch with idempotency record
        reply_task_id = str(uuid.uuid4())
        idempotency_key = f"reply-{task_id}"

        recorded = self.queue.record_outbound_task(
            task_id=reply_task_id,
            idempotency_key=idempotency_key,
            target_agent_id=requester_id,
            message=reply,
            context_id=context_id,
        )
        if not recorded:
            logger.info("Reply idempotency hit for task %s; suppressing duplicate send", task_id)
            self.queue.record_completed(event_id, reply_task_id, reply)
            return

        if self.client:
            try:
                await self.client.send_task(
                    target_agent_id=requester_id,
                    message=reply,
                    context_id=context_id,
                    task_id=reply_task_id,
                    idempotency_key=idempotency_key,
                )
                self.queue.mark_outbound_sent(idempotency_key)
                self.queue.record_completed(event_id, reply_task_id, reply)
                logger.info("Delivered A2A reply to %s for event %d", requester_id, event_id)
            except Exception as exc:
                self.queue.record_failed(event_id, f"Hub send failed: {exc}")

    async def _jev_says_no_reply(self, message: str) -> bool:
        """True only when Jev's no_reply probability clears the threshold.

        Any failure answers False so the message still reaches Brain：漏回一個
        真問題比多跑一輪 LLM 糟。題目與 eval_replacements.py 一致（自寫 16 題 16/16）。
        """
        if not self.config.a2a_jev_prefilter_enabled or not self.config.typesafe_api_key:
            return False
        from app.jev_client import jev_answer

        try:
            answer = await jev_answer(message, _A2A_REPLY_QUESTION, timeout=2.0)
        except Exception as exc:
            logger.warning("A2A Jev pre-filter failed (%s); asking Brain", type(exc).__name__)
            return False
        no_reply = (answer.get("probabilities") or {}).get("no_reply", 0.0)
        return (
            answer.get("choice") == "no_reply"
            and isinstance(no_reply, (int, float))
            and no_reply >= self.config.a2a_jev_no_reply_threshold
        )

    async def _query_brain(
        self,
        message: str,
        requester_id: str,
        task_id: str,
        context_id: str | None,
    ) -> str | None:
        """Call openVman Brain internal POST /brain/chat."""
        brain_base = self.config.brain_url.rstrip("/")
        chat_url = f"{brain_base}/brain/chat"

        prompt_with_guard = (
            f"{message}\n\n"
            f"[A2A Protocol Directive: You are replying to peer agent '{requester_id}'. "
            f"If this message is purely a confirmation, receipt, or closing statement, "
            f"output exactly {_NO_REPLY_TOKEN}. Otherwise, provide a concise and helpful response.]"
        )

        payload = {
            "message": prompt_with_guard,
            "project_id": self.config.a2a_default_project_id or "default",
            "session_id": f"a2a-{requester_id}-{context_id or task_id}",
            "stream": False,
        }
        if self.config.a2a_default_persona_id:
            payload["persona_id"] = self.config.a2a_default_persona_id

        headers = {
            "Content-Type": "application/json",
            "X-OpenVMan-User-ID": "a2a-bridge",
            "X-OpenVMan-Role": "user",
            "X-Principal-Type": "system",
            "X-Principal-Id": "a2a",
        }
        if self.config.gateway_internal_token:
            headers["X-Internal-Token"] = self.config.gateway_internal_token

        client = self._http_client or httpx.AsyncClient(timeout=60.0)
        try:
            resp = await client.post(chat_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return (data.get("reply") or data.get("text") or "").strip()
        except Exception as e:
            logger.warning("Brain query failed for A2A message from %s: %s", requester_id, e)
            return None


# Module-level singleton instance for FastAPI lifespan
_bridge_daemon: A2ABridgeDaemon | None = None


def get_a2a_bridge_daemon() -> A2ABridgeDaemon:
    global _bridge_daemon
    if _bridge_daemon is None:
        _bridge_daemon = A2ABridgeDaemon()
    return _bridge_daemon

"""SSE inbox stream ingestion, durable ACK retries, and queue processing workers for A2ABridgeDaemon."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any
import uuid

import httpx

from app.gateway.a2a_bridge_outbound import _NO_REPLY_TOKEN
from app.gateway.a2a_store import A2ACredentials

logger = logging.getLogger("backend.gateway.a2a_bridge")


class A2ABridgeInboxMixin:
    """Mixin managing SSE inbox streaming, ACK retries, orphan sweeps, and inbound event processing."""

    async def _run_sse_stream(self) -> None:
        """Connect to SSE endpoint and stream inbound events with exponential full-jitter reconnect."""
        backoff = 1.0
        while self._running and self.is_leader:
            try:
                creds = await self._ensure_credentials()
                backoff = 1.0  # Reset backoff on successful connect
                await self._stream_inbox(creds)
                if not self._running or not self.is_leader:
                    break
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._running or not self.is_leader:
                    break
                jitter = random.uniform(0.5, 1.5)
                delay = min(backoff * jitter, 30.0)
                logger.warning("A2A SSE stream interrupted: %s; reconnecting in %.1fs", exc, delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2.0, 30.0)

    async def _stream_inbox(self, creds: A2ACredentials) -> None:
        """Open persistent SSE stream and commit events before ACK."""
        if not self._http_client or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._brain_timeout_seconds, connect=10.0)
            )

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

        async with self._http_client.stream(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=httpx.Timeout(None, connect=10.0),
        ) as response:
            if response.status_code in (401, 403, 404):
                logger.warning("Hub rejected agent credentials (%d); invalidating store", response.status_code)
                self.store.clear()
                self._creds_stat = None
                if self.client is not None:
                    self.client.credentials = None
                raise RuntimeError(f"Authentication rejected: {response.status_code}")
            response.raise_for_status()

            current_event = "message"
            async for raw_line in response.aiter_lines():
                if not self._running or not self.is_leader:
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

        self._inflight_acks.add(sequence)
        dispatched = False
        try:
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

            # 2. Instant ACK dispatch (shielded so cancellation does not split HTTP ACK and DB mark)
            if self.client:
                dispatched = True
                ack_task = asyncio.create_task(self._dispatch_instant_ack(hub_scope, sequence))
                self._inflight_ack_tasks.add(ack_task)
                ack_task.add_done_callback(self._inflight_ack_tasks.discard)
                await asyncio.shield(ack_task)
        finally:
            if not dispatched:
                self._inflight_acks.discard(sequence)

    async def _dispatch_instant_ack(self, hub_scope: str, sequence: int) -> None:
        self._inflight_acks.add(sequence)
        try:
            if not self.client:
                return
            ack_ok = await self.client.acknowledge_task(sequence)
            if ack_ok:
                self.queue.mark_ack_dispatched(hub_scope, sequence)
            else:
                self.queue.record_ack_failure(hub_scope, sequence)
        finally:
            self._inflight_acks.discard(sequence)

    async def _ack_worker_loop(self) -> None:
        """Retry durable ACKs only while this process owns the bridge lease."""
        hub_scope = self._hub_scope()
        while self._running:
            try:
                if not self.is_leader:
                    await asyncio.sleep(0.5)
                    continue
                if not self.client:
                    self.get_outbound_client()
                if not self.client:
                    await asyncio.sleep(0.5)
                    continue
                pending = self.queue.get_pending_ack_events(hub_scope, limit=20)
                ready = [ev for ev in pending if int(ev["sequence"]) not in self._inflight_acks]
                if not ready:
                    await asyncio.sleep(0.5)
                    continue
                did_work = False
                for event in ready:
                    if not self._running or not self.is_leader:
                        break
                    sequence = int(event["sequence"])
                    if sequence in self._inflight_acks:
                        continue
                    did_work = True
                    if await self.client.acknowledge_task(sequence):
                        self.queue.mark_ack_dispatched(hub_scope, sequence)
                    else:
                        self.queue.record_ack_failure(hub_scope, sequence, retry_after_seconds=2.0)
                if not did_work:
                    await asyncio.sleep(0.5)
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
                if not self.is_leader:
                    await asyncio.sleep(0.5)
                    continue
                if self._pending_requeue and not self._run_pending_requeue(reason="worker loop retry"):
                    await asyncio.sleep(0.5)
                    continue
                if not self.client:
                    self.get_outbound_client()
                if not self.client:
                    await asyncio.sleep(0.5)
                    continue
                now_mono = self._monotonic()
                if now_mono - self._last_orphan_sweep >= self._orphan_sweep_interval_seconds:
                    recovered_orphans = self.queue.requeue_orphaned_local_events(
                        hub_scope,
                        self.worker_id,
                        set(self._active_event_ids),
                    )
                    if recovered_orphans:
                        logger.warning(
                            "Recovered %d orphaned local A2A processing event(s) (worker=%s)",
                            recovered_orphans,
                            self.worker_id,
                        )
                    self._last_orphan_sweep = now_mono
                if now_mono - self._last_queue_prune > 300:
                    self.queue.prune_terminal_events(self.config.a2a_queue_retention_days)
                    self._last_queue_prune = now_mono
                events = self.queue.get_unprocessed_events(hub_scope, limit=self.config.a2a_max_concurrency)
                if not events:
                    await asyncio.sleep(0.5)
                    continue

                async def _process_single(event: dict[str, Any]) -> None:
                    async with sem:
                        if not self._running or not self.is_leader or self._pending_requeue:
                            return
                        await self._process_queued_event(event, require_leader=True)

                batch_tasks: list[asyncio.Task[None]] = []
                for ev in events:
                    task = asyncio.create_task(_process_single(ev))
                    self._processing_tasks.add(task)
                    task.add_done_callback(self._processing_tasks.discard)
                    batch_tasks.append(task)
                batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                for res in batch_results:
                    if isinstance(res, Exception) and not isinstance(res, asyncio.CancelledError):
                        logger.error("Unhandled A2A worker task exception: %s", res, exc_info=res)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Queue worker loop error: %s", exc)
                await asyncio.sleep(1.0)

    async def _process_queued_event(
        self,
        event: dict[str, Any],
        *,
        require_leader: bool = False,
    ) -> None:
        """Process one event: Anti-Echo check -> Brain chat -> Reply send."""
        if require_leader and (not self._running or not self.is_leader or self._pending_requeue):
            return

        event_id = int(event["id"])
        message = event["message"]
        requester_id = event["requester_agent_id"]
        context_id = event.get("context_id")
        task_id = event["task_id"]

        self._active_event_ids.add(event_id)
        try:
            started = self.queue.record_processing_start(event_id, worker_id=self.worker_id)
        except Exception:
            self._active_event_ids.discard(event_id)
            raise
        if not started:
            self._active_event_ids.discard(event_id)
            return

        dispatched_reply = False
        try:
            cached_reply = event.get("reply_message")
            cached_reply_task_id = event.get("reply_task_id")

            if cached_reply:
                reply = str(cached_reply)
                reply_task_id = str(cached_reply_task_id) if cached_reply_task_id else str(uuid.uuid4())
                if not cached_reply_task_id:
                    self.queue.record_reply_prepared(
                        event_id,
                        reply_task_id,
                        reply,
                        worker_id=self.worker_id,
                    )
            else:
                if require_leader and (not self._running or not self.is_leader):
                    self._revert_processing_safely(event_id)
                    return

                # 1. Forward peer content to Brain; Brain decides suppression.
                reply = await self._query_brain(
                    message,
                    requester_id=requester_id,
                    task_id=task_id,
                    context_id=context_id,
                )
                if require_leader and (not self._running or not self.is_leader):
                    self._revert_processing_safely(event_id)
                    return
                if not reply:
                    self.queue.record_failed(event_id, "Brain returned empty reply", worker_id=self.worker_id)
                    return

                # 3. Exact [[A2A_NO_REPLY]] token suppression
                if _NO_REPLY_TOKEN in reply:
                    logger.info("Brain returned [[A2A_NO_REPLY]] for event %d; dialogue ended", event_id)
                    self.queue.record_suppressed(event_id, "token", worker_id=self.worker_id)
                    return

                reply_task_id = str(uuid.uuid4())
                if not self.queue.record_reply_prepared(
                    event_id,
                    reply_task_id,
                    reply,
                    worker_id=self.worker_id,
                ):
                    return

            # 4. Outbound reply dispatch with idempotency record
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
                self.queue.record_completed(event_id, reply_task_id, reply, worker_id=self.worker_id)
                return

            if self.client or not self._has_injected_client:
                if require_leader and (not self._running or not self.is_leader):
                    self._revert_processing_safely(event_id)
                    return
                dispatched_reply = True
                reply_task = asyncio.create_task(
                    self._dispatch_outbound_reply(
                        event_id=event_id,
                        requester_id=requester_id,
                        reply=reply,
                        context_id=context_id,
                        reply_task_id=reply_task_id,
                        idempotency_key=idempotency_key,
                    )
                )
                self._inflight_replies.add(reply_task)
                reply_task.add_done_callback(self._inflight_replies.discard)
                await asyncio.shield(reply_task)
        except asyncio.CancelledError:
            if not dispatched_reply:
                self._revert_processing_safely(event_id)
            raise
        except Exception as exc:
            logger.exception("Unhandled error processing A2A event %s: %s", event_id, exc)
            self._record_outbound_failure(event_id, f"Unhandled processing error: {exc}")
        finally:
            if not dispatched_reply:
                self._active_event_ids.discard(event_id)

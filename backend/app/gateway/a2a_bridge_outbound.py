"""Outbound Hub credential resolution, reply dispatch/retry, and Brain chat forwarding for A2ABridgeDaemon."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
from typing import TypeVar

import httpx

from app.gateway.a2a_client import A2AClient, A2ARateLimitError
from app.gateway.a2a_store import A2ACredentials
from app.project_ids import DEFAULT_PROJECT_ALIAS, canonical_project_id

logger = logging.getLogger("backend.gateway.a2a_bridge")

T = TypeVar("T")

_NO_REPLY_TOKEN = "[[A2A_NO_REPLY]]"


class A2ACredentialsUnavailableError(RuntimeError):
    """Raised when A2A Hub credentials are missing, cleared, or rejected after reload."""


def _parse_retry_after_seconds(
    response: httpx.Response,
    default: float = 2.0,
    max_seconds: float = 60.0,
) -> float:
    raw = response.headers.get("Retry-After", "").strip()
    if not raw:
        return min(max_seconds, max(0.5, default))
    try:
        return min(max_seconds, max(0.5, float(raw)))
    except ValueError:
        try:
            target_dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return min(max_seconds, max(0.5, default))
        if target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=timezone.utc)
        delay = target_dt.timestamp() - datetime.now(timezone.utc).timestamp()
        return min(max_seconds, max(0.5, delay))


class A2ABridgeOutboundMixin:
    """Mixin managing outbound Hub client lifecycle, credential reloads, reply delivery, and Brain calls."""

    def _file_stat_key(self) -> tuple[int, int, int] | None:
        try:
            st = self.store.filepath.stat()
            return (st.st_mtime_ns, getattr(st, "st_ino", 0), st.st_size)
        except OSError:
            return None

    def _build_client(self, creds: A2ACredentials | None = None) -> A2AClient:
        return A2AClient(
            hub_url=self.config.a2a_hub_url,
            hub_key=self.config.a2a_hub_key,
            credentials=creds,
            max_concurrency=self.config.a2a_max_concurrency,
            max_tasks_per_minute=self.config.a2a_max_tasks_per_minute,
        )

    def get_outbound_client(self, *, force_reload: bool = False) -> A2AClient | None:
        """Lazily load or mtime-reload an outbound A2AClient from the shared credential store."""
        stat_key = self._file_stat_key()
        if stat_key is None:
            if self._creds_stat is not None:
                self._creds_stat = None
                if self.client is not None:
                    self.client.credentials = None
                return None
            if (
                not force_reload
                and self.client is not None
                and (
                    self._has_injected_client
                    or getattr(self.client, "credentials", None) is not None
                )
            ):
                return self.client
            return None

        if (
            force_reload
            or self.client is None
            or (not self._has_injected_client and getattr(self.client, "credentials", None) is None)
            or self._creds_stat != stat_key
        ):
            creds = self.store.load(
                expected_hub_url=self.config.a2a_hub_url,
                current_hub_key=self.config.a2a_hub_key,
            )
            if creds is None:
                self._creds_stat = None
                if self.client is not None:
                    self.client.credentials = None
                return None
            self._creds_stat = stat_key
            if self.client is None:
                self.client = self._build_client(creds)
            else:
                self.client.credentials = creds
        return self.client

    async def call_outbound(self, operation: Callable[[A2AClient], Awaitable[T]]) -> T:
        """Execute an outbound Hub operation, reloading credentials on change or 401/403."""
        client = self.get_outbound_client(force_reload=False)
        if client is None:
            client = self.get_outbound_client(force_reload=True)
        if client is None:
            raise A2ACredentialsUnavailableError(
                "A2A credentials are unavailable or invalid; waiting for leader registration"
            )

        async def _invoke(target_client: A2AClient) -> T:
            try:
                return await operation(target_client)
            except RuntimeError as exc:
                if "credentials missing" in str(exc).lower():
                    raise A2ACredentialsUnavailableError(str(exc)) from exc
                raise

        try:
            return await _invoke(client)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (401, 403):
                raise
            reloaded = self.get_outbound_client(force_reload=True)
            if reloaded is None:
                raise A2ACredentialsUnavailableError(
                    f"A2A hub rejected credentials ({exc.response.status_code}) and no valid credentials were found on reload"
                ) from exc
            try:
                retry_client = (
                    reloaded.for_retry()
                    if isinstance(getattr(reloaded, "_skip_rate_limit", None), bool)
                    else reloaded
                )
                return await _invoke(retry_client)
            except httpx.HTTPStatusError as retry_exc:
                if retry_exc.response.status_code in (401, 403):
                    raise A2ACredentialsUnavailableError(
                        f"A2A hub rejected credentials ({retry_exc.response.status_code}) after reloading credentials"
                    ) from retry_exc
                raise

    async def _ensure_credentials(self) -> A2ACredentials:
        """Load from encrypted store or register freshly with Hub (leader only)."""
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
                self.client = self._build_client(creds)
            else:
                self.client.credentials = creds
            self._creds_stat = self._file_stat_key()
            return creds

        if not self.client:
            self.client = self._build_client()
        creds = await self.client.register(
            display_name=self.config.a2a_display_name,
            idempotency_key=f"openvman-registration-{self._hub_scope()[:24]}",
            fingerprint_key=self.config.a2a_credentials_encryption_key or self.config.session_jwt_secret,
        )
        self.store.save(creds)
        self._creds_stat = self._file_stat_key()
        return creds

    def _revert_processing_safely(self, event_id: int) -> None:
        try:
            self.queue.revert_processing_start(event_id, worker_id=self.worker_id)
        except Exception as db_exc:
            logger.debug("revert_processing_start failed for event %s: %s", event_id, db_exc)

    def _record_outbound_failure(self, event_id: int, message: str) -> None:
        try:
            self.queue.record_failed(event_id, message, worker_id=self.worker_id)
        except Exception as db_exc:
            logger.warning(
                "record_failed failed for event %s (%s); attempting revert_processing_start",
                event_id,
                db_exc,
            )
            self._revert_processing_safely(event_id)

    def _record_outbound_rate_limited(
        self,
        event_id: int,
        retry_after_seconds: float,
        *,
        reply_task_id: str,
        reply_message: str,
    ) -> None:
        try:
            self.queue.record_rate_limited(
                event_id,
                retry_after_seconds,
                reply_task_id=reply_task_id,
                reply_message=reply_message,
                worker_id=self.worker_id,
            )
        except Exception as db_exc:
            logger.warning(
                "record_rate_limited failed for event %s (%s); attempting revert_processing_start",
                event_id,
                db_exc,
            )
            self._revert_processing_safely(event_id)

    async def _dispatch_outbound_reply(
        self,
        *,
        event_id: int,
        requester_id: str,
        reply: str,
        context_id: str | None,
        reply_task_id: str,
        idempotency_key: str,
    ) -> None:
        """Deliver reply via call_outbound and commit outbound/completed status atomically across stop()."""
        if not self.client and self._has_injected_client:
            self._active_event_ids.discard(event_id)
            return
        try:
            await self.call_outbound(
                lambda c: c.send_task(
                    target_agent_id=requester_id,
                    message=reply,
                    context_id=context_id,
                    task_id=reply_task_id,
                    idempotency_key=idempotency_key,
                )
            )
            self.queue.mark_outbound_sent(idempotency_key)
            if self.queue.record_completed(event_id, reply_task_id, reply, worker_id=self.worker_id):
                logger.info("Delivered A2A reply to %s for event %d", requester_id, event_id)
            else:
                logger.warning(
                    "Delivered A2A reply for event %d, but processing ownership changed before completion commit",
                    event_id,
                )
        except asyncio.CancelledError:
            self._revert_processing_safely(event_id)
            raise
        except A2ARateLimitError as exc:
            retry_after = min(60.0, max(0.5, float(exc.retry_after)))
            logger.warning(
                "A2A reply for event %d deferred %.2fs by local rate limiter",
                event_id,
                retry_after,
            )
            self._record_outbound_rate_limited(
                event_id,
                retry_after,
                reply_task_id=reply_task_id,
                reply_message=reply,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                retry_after = _parse_retry_after_seconds(exc.response, default=2.0, max_seconds=60.0)
                logger.warning(
                    "A2A reply for event %d deferred %.2fs by Hub HTTP 429",
                    event_id,
                    retry_after,
                )
                self._record_outbound_rate_limited(
                    event_id,
                    retry_after,
                    reply_task_id=reply_task_id,
                    reply_message=reply,
                )
            else:
                logger.warning("Hub rejected A2A reply for event %d (%d): %s", event_id, exc.response.status_code, exc)
                self._record_outbound_failure(event_id, f"Hub send failed: {exc}")
        except Exception as exc:
            logger.warning("Failed sending A2A reply for event %d: %s", event_id, exc)
            self._record_outbound_failure(event_id, f"Hub send failed: {exc}")
        finally:
            self._active_event_ids.discard(event_id)

    async def _query_brain(
        self,
        message: str,
        requester_id: str,
        task_id: str,
        context_id: str | None,
    ) -> str | None:
        """Call openVman Brain internal POST /brain/chat."""
        brain_base = self.config.resolved_brain_chat_url.rstrip("/")
        chat_url = f"{brain_base}/brain/chat"

        prompt_with_guard = (
            f"{message}\n\n"
            f"[A2A Protocol Directive: You are replying to peer agent '{requester_id}'. "
            f"If this message is purely a confirmation, receipt, or closing statement, "
            f"output exactly {_NO_REPLY_TOKEN}. Otherwise, provide a concise and helpful response.]"
        )

        payload = {
            "message": prompt_with_guard,
            "project_id": canonical_project_id(
                self.config.a2a_default_project_id or DEFAULT_PROJECT_ALIAS
            ),
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

        timeout_seconds = float(
            getattr(
                self,
                "_brain_timeout_seconds",
                getattr(self.config, "a2a_brain_timeout_seconds", 60.0),
            )
        )
        brain_timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        http_client = getattr(self, "_http_client", None)
        owns_client = http_client is None or bool(getattr(http_client, "is_closed", False))
        client = httpx.AsyncClient(timeout=brain_timeout) if owns_client else http_client
        assert client is not None
        try:
            resp = await client.post(
                chat_url,
                json=payload,
                headers=headers,
                timeout=brain_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return (data.get("reply") or data.get("text") or "").strip()
        except Exception as e:
            logger.warning("Brain query failed for A2A message from %s: %s", requester_id, e)
            return None
        finally:
            if owns_client:
                await client.aclose()

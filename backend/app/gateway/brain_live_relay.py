"""Backend-to-brain live relay for gemini_live sessions."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse, urlunparse

import websockets

from app.config import TTSRouterConfig, get_tts_config
from app.providers.base import SynthesizeRequest
from app.service import TTSRouterService
from app.session_manager import Session

logger = logging.getLogger("backend.brain_live_relay")

EventSink = Callable[[dict[str, Any]], Awaitable[None]]
DEFAULT_VOICE_SOURCE = "gemini"
CUSTOM_VOICE_SOURCE = "custom"


def _normalize_voice_source(voice_source: str) -> str:
    if voice_source in {DEFAULT_VOICE_SOURCE, CUSTOM_VOICE_SOURCE}:
        return voice_source
    return DEFAULT_VOICE_SOURCE


def _build_brain_live_ws_url(brain_url: str, relay_session_id: str) -> str:
    parsed = urlparse(brain_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = f"{parsed.path.rstrip('/')}/brain/internal/live/{relay_session_id}"
    return urlunparse((scheme, parsed.netloc, path, "", "", ""))


class BrainLiveRelay:
    """Persistent internal websocket relay to the Brain live bridge."""

    def __init__(
        self,
        session: Session,
        *,
        config: TTSRouterConfig | None = None,
        voice_source: str = DEFAULT_VOICE_SOURCE,
        tts_service: TTSRouterService | None = None,
        websocket_factory: Any | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self.session = session
        self.config = config or get_tts_config()
        self.voice_source = _normalize_voice_source(voice_source)
        self._tts_service = tts_service
        self._websocket_factory = websocket_factory or websockets.connect
        self._event_sink = event_sink
        self._ws: Any | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._tts_queue: asyncio.Queue[dict[str, Any]] | None = None
        self._tts_worker_task: asyncio.Task[None] | None = None
        self._closed = False
        self._connect_lock = asyncio.Lock()

    async def ensure_connected(self) -> None:
        if self._ws is not None:
            return
        async with self._connect_lock:
            if self._ws is not None:
                return

            url = _build_brain_live_ws_url(
                self.config.brain_url,
                self.session.session_id,
            )
            self._ws = await self._websocket_factory(
                url,
                open_timeout=10,
                max_size=4 * 1024 * 1024,
            )
            relay_init: dict[str, Any] = {
                "event": "relay_init",
                "session_id": self.session.session_id,
                "client_id": self.session.client_id,
                "persona_id": str(self.session.metadata.get("persona_id", "default")),
                "project_id": str(self.session.metadata.get("project_id", "default")),
            }
            chat_session_id = str(self.session.metadata.get("chat_session_id", "")).strip()
            if chat_session_id:
                relay_init["chat_session_id"] = chat_session_id
            await self._send_json(relay_init)

            if self._event_sink is not None and self._listener_task is None:
                self._listener_task = asyncio.create_task(self._listen())

    async def send_event(self, payload: dict[str, Any]) -> None:
        await self.ensure_connected()
        await self._send_json(payload)

    async def close(self) -> None:
        self._closed = True
        for task in (self._listener_task, self._tts_worker_task):
            await self._cancel_task(task)
        self._listener_task = None
        self._tts_worker_task = None
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _listen(self) -> None:
        try:
            while self._ws is not None:
                message = await self._ws.recv()
                if isinstance(message, bytes):
                    message = message.decode("utf-8")
                payload = json.loads(message)
                if self._event_sink is None:
                    continue
                if self._should_intercept_chunk(payload):
                    await self._enqueue_tts_chunk(payload)
                    continue
                await self._event_sink(payload)
        except websockets.ConnectionClosed:
            if not self._closed and self._event_sink is not None:
                logger.warning("brain live relay disconnected for session=%s", self.session.session_id)
                await self._event_sink(
                    {
                        "event": "server_error",
                        "error_code": "INTERNAL_ERROR",
                        "message": "Brain live relay disconnected",
                        "timestamp": int(time.time() * 1000),
                    }
                )
        finally:
            self._ws = None

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("Brain live relay is not connected")
        await self._ws.send(json.dumps(payload))

    def _should_intercept_chunk(self, payload: dict[str, Any]) -> bool:
        return self.voice_source == CUSTOM_VOICE_SOURCE and payload.get("event") == "server_stream_chunk"

    async def _enqueue_tts_chunk(self, payload: dict[str, Any]) -> None:
        queue = self._ensure_tts_worker()
        await queue.put(payload)

    async def _tts_worker(self) -> None:
        if self._tts_queue is None:
            return

        while not self._closed:
            payload = await self._tts_queue.get()
            try:
                if not self._closed:
                    await self._emit_tts_chunk(payload)
            finally:
                self._tts_queue.task_done()

    def _handle_tts_worker_done(self, task: asyncio.Task[None]) -> None:
        if self._tts_worker_task is task:
            self._tts_worker_task = None
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("TTS worker crashed for session=%s: %s", self.session.session_id, exc)

    async def _emit_tts_chunk(self, payload: dict[str, Any]) -> None:
        if self._event_sink is None:
            return

        text = payload.get("text", "")
        audio_base64 = ""
        if text:
            try:
                audio_base64 = await self._synthesize_audio_base64(text)
            except Exception as exc:
                logger.warning(
                    "custom live TTS synthesis failed for session=%s: %s",
                    self.session.session_id,
                    exc,
                )

        await self._event_sink(
            {
                **payload,
                "audio_base64": audio_base64,
            }
        )

    async def _synthesize_audio_base64(self, text: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._synthesize_audio_base64_sync, text)

    def _synthesize_audio_base64_sync(self, text: str) -> str:
        output = self._get_tts_service().synthesize(SynthesizeRequest(text=text))
        return base64.b64encode(output.result.audio_bytes).decode("utf-8")

    async def _cancel_task(self, task: asyncio.Task[Any] | None) -> None:
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    def _ensure_tts_worker(self) -> asyncio.Queue[dict[str, Any]]:
        if self._tts_queue is None:
            self._tts_queue = asyncio.Queue()
        if self._tts_worker_task is None or self._tts_worker_task.done():
            self._tts_worker_task = asyncio.create_task(self._tts_worker())
            self._tts_worker_task.add_done_callback(self._handle_tts_worker_done)
        return self._tts_queue

    def _get_tts_service(self) -> TTSRouterService:
        if self._tts_service is None:
            self._tts_service = TTSRouterService(self.config)
        return self._tts_service

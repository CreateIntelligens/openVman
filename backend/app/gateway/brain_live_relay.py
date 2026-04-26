"""Backend-to-brain live relay for gemini_live sessions.

Pure passthrough: forwards LLM text events from the brain bridge to the
client websocket untouched. TTS synthesis lives entirely on the frontend
via the `/tts_stream` endpoint.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse, urlunparse

import websockets

from app.config import TTSRouterConfig, get_tts_config
from app.session_manager import Session

logger = logging.getLogger("backend.brain_live_relay")

EventSink = Callable[[dict[str, Any]], Awaitable[None]]

# Client-declared voice source values stored in session.metadata.
# The relay does not branch on these — frontend decides TTS behavior.
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
        websocket_factory: Any | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self.session = session
        self.config = config or get_tts_config()
        self._websocket_factory = websocket_factory or websockets.connect
        self._event_sink = event_sink
        self._ws: Any | None = None
        self._listener_task: asyncio.Task[None] | None = None
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
        await self._cancel_task(self._listener_task)
        self._listener_task = None
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
                # Strip upstream audio: the frontend synthesizes speech via
                # /tts_stream after receiving the text. Forwarding the original
                # Gemini audio would cause double playback.
                if payload.get("event") == "server_stream_chunk" and payload.get("audio_base64"):
                    payload = {**payload, "audio_base64": ""}
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

    async def _cancel_task(self, task: asyncio.Task[Any] | None) -> None:
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

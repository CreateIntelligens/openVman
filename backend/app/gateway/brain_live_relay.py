"""Backend-to-brain live relay for gemini_live sessions."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse, urlunparse

import websockets

from app.config import TTSRouterConfig, get_tts_config
from app.session_manager import Session

logger = logging.getLogger("backend.brain_live_relay")

EventSink = Callable[[dict[str, Any]], Awaitable[None]]


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
        self._listener_task: Any | None = None
        self._closed = False

    async def ensure_connected(self) -> None:
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
        await self._send_json(
            {
                "event": "relay_init",
                "session_id": self.session.session_id,
                "client_id": self.session.client_id,
                "persona_id": str(self.session.metadata.get("persona_id", "default")),
                "project_id": str(self.session.metadata.get("project_id", "default")),
            }
        )

        if self._event_sink is not None and self._listener_task is None:
            self._listener_task = asyncio.create_task(self._listen())

    async def send_event(self, payload: dict[str, Any]) -> None:
        await self.ensure_connected()
        await self._send_json(payload)

    async def close(self) -> None:
        self._closed = True
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except Exception:
                pass
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
                if self._event_sink is not None:
                    await self._event_sink(payload)
        except websockets.ConnectionClosed:
            if not self._closed:
                logger.warning("brain live relay disconnected for session=%s", self.session.session_id)
                if self._event_sink is not None:
                    await self._event_sink(
                        {
                            "event": "server_error",
                            "error_code": "internal_error",
                            "message": "Brain live relay disconnected",
                        }
                    )
        finally:
            self._ws = None

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("Brain live relay is not connected")
        await self._ws.send(json.dumps(payload))

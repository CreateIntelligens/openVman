"""JSON websocket transport for the Gemini Live wire API."""

from __future__ import annotations

import json
from typing import Any, Protocol

import websockets

from config import BrainSettings


_GEMINI_LIVE_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)


class JsonTransport(Protocol):
    async def connect(self) -> None: ...

    async def send_json(self, payload: dict[str, Any]) -> None: ...

    async def recv_json(self) -> dict[str, Any] | None: ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class GeminiLiveWebSocketTransport:
    """Minimal JSON transport for Gemini Live's raw websocket API."""

    def __init__(self, config: BrainSettings) -> None:
        self._config = config
        self._ws: Any | None = None

    async def connect(self) -> None:
        if not self._config.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        self._ws = await websockets.connect(
            _GEMINI_LIVE_WS_URL,
            additional_headers={"x-goog-api-key": self._config.gemini_api_key},
            open_timeout=10,
            max_size=4 * 1024 * 1024,
        )

    async def send_json(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("Gemini Live transport is not connected")
        await self._ws.send(json.dumps(payload))

    async def recv_json(self) -> dict[str, Any] | None:
        if self._ws is None:
            raise RuntimeError("Gemini Live transport is not connected")
        try:
            message = await self._ws.recv()
        except websockets.ConnectionClosedOK:
            return None
        except websockets.ConnectionClosedError as exc:
            raise RuntimeError(f"Gemini Live websocket closed: {exc}") from exc
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        return json.loads(message)

    async def ping(self) -> None:
        if self._ws is None:
            raise RuntimeError("Gemini Live transport is not connected")
        pong = await self._ws.ping()
        await pong

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

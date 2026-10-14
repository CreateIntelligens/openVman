"""Tell route handlers when the HTTP client has gone away.

Starlette's ``request.is_disconnected()`` never turns true behind
``BaseHTTPMiddleware`` (``app.middleware("http")``): the wrapper swallows the
disconnect message when it is polled. This pure ASGI middleware sits outside
those wrappers, watches the raw ``receive`` once the request body has been
read, and records the disconnect on the scope where handlers can await it.

Backend carries its own copy (``backend/app/client_disconnect.py``) because
the two services do not share Python code.
"""

from __future__ import annotations

import asyncio
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

SCOPE_KEY = "openvman.client_disconnected"
DEFAULT_POLL_INTERVAL_S = 0.25


class ClientDisconnectMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        disconnected = asyncio.Event()
        scope[SCOPE_KEY] = disconnected
        body_done = False
        watcher: asyncio.Task[None] | None = None

        async def watch() -> None:
            # After the body only http.disconnect can arrive (the server also
            # sends it once the response is complete, when nobody cares).
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    disconnected.set()
                    return

        async def wrapped_receive() -> Message:
            nonlocal body_done, watcher
            if body_done:
                # The watcher owns the raw receive now; hand downstream readers
                # (StreamingResponse, BaseHTTPMiddleware) the same disconnect.
                await disconnected.wait()
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected.set()
            elif not message.get("more_body", False):
                body_done = True
                watcher = asyncio.create_task(watch())
            return message

        try:
            await self.app(scope, wrapped_receive, send)
        finally:
            if watcher is not None:
                watcher.cancel()


async def wait_for_client_disconnect(
    request: Any, *, poll_interval: float = DEFAULT_POLL_INTERVAL_S,
) -> None:
    """Return once the client of *request* has disconnected; never returns otherwise.

    Uses the middleware's event when present, else polls ``is_disconnected()``.
    """
    scope = getattr(request, "scope", None)
    event = scope.get(SCOPE_KEY) if isinstance(scope, dict) else None
    if isinstance(event, asyncio.Event):
        await event.wait()
        return
    is_disconnected = getattr(request, "is_disconnected", None)
    if is_disconnected is None:
        await asyncio.Event().wait()
        return
    while not await is_disconnected():
        await asyncio.sleep(poll_interval)

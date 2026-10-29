"""The Brain proxy must hang up on Brain when its own caller hangs up.

整合方與數位人前端在使用者打斷時會 abort fetch；Backend 以前照樣等 Brain
把整輪生成跑完，Brain 因此看不到斷線、繼續花 LLM 與工具的時間。
"""

from __future__ import annotations

import json

import asyncio
import logging
import os
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi import Request as FastAPIRequest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import brain_proxy
from app.client_disconnect import (
    SCOPE_KEY,
    ClientDisconnectMiddleware,
    wait_for_client_disconnect,
)


def _mock_cfg() -> MagicMock:
    return MagicMock(
        brain_url="http://brain:8100",
        gateway_internal_token="internal-secret",
        brain_proxy_max_body_bytes=110 * 1024 * 1024,
    )


class _LeavingRequest(Request):
    """A chat request whose client disconnects *leave_after* seconds after it is first polled."""

    def __init__(self, leave_after: float | None, *, scope_event: asyncio.Event | None = None):
        scope: dict[str, Any] = {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/chat",
            "raw_path": b"/api/v1/chat",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        if scope_event is not None:
            scope[SCOPE_KEY] = scope_event
        body_sent = False

        async def receive() -> dict[str, Any]:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": b'{"message":"hi"}', "more_body": False}
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        super().__init__(scope, receive)
        self._leave_after = leave_after
        self._first_poll: float | None = None
        self.polls = 0

    async def is_disconnected(self) -> bool:
        self.polls += 1
        if self._leave_after is None:
            return False
        now = time.monotonic()
        if self._first_poll is None:
            self._first_poll = now
        return now - self._first_poll >= self._leave_after


class _HangingUpstream:
    """httpx client stand-in whose Brain never answers; records the cancellation."""

    def __init__(self) -> None:
        self.cancelled = asyncio.Event()

    def build_request(self, **kwargs: Any) -> str:
        return "request"

    async def send(self, request: Any, *, stream: bool) -> Any:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


def _upstream_response(body: bytes = b'{"status":"ok"}') -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.headers = {"content-type": "application/json"}
    response.aread = AsyncMock(return_value=body)
    response.aclose = AsyncMock(return_value=None)
    return response


def _proxy(request: Request, client: Any) -> Any:
    async def run() -> tuple[Any, float]:
        started = time.monotonic()
        with (
            patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
            patch("app.brain_proxy._http.get", return_value=client),
        ):
            response = await asyncio.wait_for(
                brain_proxy.proxy_to_brain(request, "chat", current=None), timeout=5,
            )
        return response, time.monotonic() - started

    return asyncio.run(run())


def test_client_disconnect_cancels_the_pending_brain_request(caplog) -> None:
    upstream = _HangingUpstream()
    request = _LeavingRequest(leave_after=0.3)

    with caplog.at_level(logging.INFO, logger="backend.brain_proxy"):
        response, elapsed = _proxy(request, upstream)

    assert response.status_code == brain_proxy.CLIENT_CLOSED_REQUEST
    assert upstream.cancelled.is_set()
    assert elapsed < 1.5
    disconnect_logs = [r for r in caplog.records if "client disconnected" in r.getMessage()]
    assert len(disconnect_logs) == 1


def test_middleware_event_cancels_without_polling() -> None:
    upstream = _HangingUpstream()
    event = asyncio.Event()
    request = _LeavingRequest(leave_after=None, scope_event=event)

    async def run() -> Any:
        asyncio.get_running_loop().call_later(0.05, event.set)
        with (
            patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
            patch("app.brain_proxy._http.get", return_value=upstream),
        ):
            return await asyncio.wait_for(
                brain_proxy.proxy_to_brain(request, "chat", current=None), timeout=5,
            )

    response = asyncio.run(run())

    assert response.status_code == brain_proxy.CLIENT_CLOSED_REQUEST
    assert upstream.cancelled.is_set()
    assert request.polls == 0


def test_disconnect_while_reading_the_body_closes_the_upstream_response() -> None:
    upstream_response = _upstream_response()

    async def slow_body() -> bytes:
        await asyncio.Event().wait()
        return b""

    upstream_response.aread = slow_body
    client = MagicMock()
    client.build_request = MagicMock(return_value="request")
    client.send = AsyncMock(return_value=upstream_response)

    response, _ = _proxy(_LeavingRequest(leave_after=0.1), client)

    assert response.status_code == brain_proxy.CLIENT_CLOSED_REQUEST
    upstream_response.aclose.assert_awaited()


def test_connected_client_gets_brain_reply_without_waiting_for_a_poll() -> None:
    client = MagicMock()
    client.build_request = MagicMock(return_value="request")
    client.send = AsyncMock(return_value=_upstream_response(b'{"reply":"ok"}'))

    response, elapsed = _proxy(_LeavingRequest(leave_after=None), client)

    assert response.status_code == 200
    # /chat 的回應會多帶念的版本 tts_text。
    assert json.loads(response.body) == {"reply": "ok", "tts_text": "ok"}
    # 回應到了就回，不等下一次斷線輪詢（0.25 秒）。
    assert elapsed < 0.2


@pytest.fixture()
def app_client():
    with patch.dict(os.environ, {"BRAIN_URL": "http://brain:8100"}, clear=False):
        from app.config import get_tts_config

        get_tts_config.cache_clear()
        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


def test_sse_responses_still_stream_through_the_app(app_client: TestClient) -> None:
    upstream = MagicMock()
    upstream.status_code = 200
    upstream.headers = {"content-type": "text/event-stream"}
    upstream.aclose = AsyncMock(return_value=None)

    async def chunks():
        yield b"data: one\n\n"
        yield b"data: two\n\n"

    upstream.aiter_bytes = MagicMock(return_value=chunks())
    client = MagicMock()
    client.build_request = MagicMock(return_value="request")
    client.send = AsyncMock(return_value=upstream)

    with (
        patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
        patch("app.brain_proxy._http.get", return_value=client),
    ):
        response = app_client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.text == "data: one\n\ndata: two\n\n"
    upstream.aclose.assert_awaited()


# ---------------------------------------------------------------------------
# ClientDisconnectMiddleware
# ---------------------------------------------------------------------------

def _app_behind_base_http_middleware(seen: dict[str, Any]) -> FastAPI:
    app = FastAPI()

    @app.post("/chat")
    async def chat(request: FastAPIRequest) -> dict[str, bool]:
        await request.body()
        try:
            await asyncio.wait_for(wait_for_client_disconnect(request), timeout=1)
            seen["disconnected"] = True
        except asyncio.TimeoutError:
            seen["disconnected"] = False
        return {"ok": True}

    async def passthrough(request, call_next):
        return await call_next(request)

    # 跟正式 app 一樣：BaseHTTPMiddleware 會吞掉斷線訊息，所以這層要在最外面。
    app.middleware("http")(passthrough)
    app.add_middleware(ClientDisconnectMiddleware)
    return app


def _run_asgi(app: FastAPI, *, leave_after: float | None) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def run() -> None:
        leave = asyncio.Event()
        pending = [{"type": "http.request", "body": b"{}", "more_body": False}]
        response_done = asyncio.Event()

        async def receive() -> dict[str, Any]:
            if pending:
                return pending.pop(0)
            waiters = [asyncio.ensure_future(leave.wait()), asyncio.ensure_future(response_done.wait())]
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            for waiter in waiters:
                waiter.cancel()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)
            if message["type"] == "http.response.body" and not message.get("more_body"):
                response_done.set()

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "method": "POST", "scheme": "http",
            "path": "/chat", "raw_path": b"/chat", "root_path": "", "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("testclient", 50000), "server": ("testserver", 80),
        }
        if leave_after is not None:
            asyncio.get_running_loop().call_later(leave_after, leave.set)
        await asyncio.wait_for(app(scope, receive, send), timeout=5)

    asyncio.run(run())
    return sent


def test_middleware_sees_disconnect_behind_base_http_middleware() -> None:
    seen: dict[str, Any] = {}

    _run_asgi(_app_behind_base_http_middleware(seen), leave_after=0.05)

    assert seen == {"disconnected": True}


def test_middleware_reports_nothing_while_the_client_stays() -> None:
    seen: dict[str, Any] = {}

    sent = _run_asgi(_app_behind_base_http_middleware(seen), leave_after=None)

    assert seen == {"disconnected": False}
    assert sent[0]["status"] == 200


def test_backend_app_installs_the_middleware_outermost() -> None:
    from app.main import app

    assert app.user_middleware[0].cls is ClientDisconnectMiddleware

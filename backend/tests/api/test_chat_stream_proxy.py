"""/api/v1/chat/stream must reach Brain like /chat and stream each event as it comes.

整合方拿第一句就要開始 TTS：Backend 只要把回應整段收完才轉發，逐句串流就失效了。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI

from app import brain_proxy
from app.auth.dependencies import get_current_account
from app.auth.embed import is_allowlisted
from app.client_disconnect import ClientDisconnectMiddleware

_FIRST = b'event: sentence\ndata: {"index": 0, "text": "\xe7\xac\xac\xe4\xb8\x80\xe5\x8f\xa5\xe3\x80\x82"}\n\n'
_DONE = b'event: done\ndata: {"reply": "\xe7\xac\xac\xe4\xb8\x80\xe5\x8f\xa5\xe3\x80\x82"}\n\n'


def _mock_cfg() -> MagicMock:
    return MagicMock(brain_url="http://brain:8100", gateway_internal_token="internal-secret")


def _proxy_app() -> FastAPI:
    """The proxy router behind the same middleware layers production uses."""
    app = FastAPI()
    app.include_router(brain_proxy.router)
    app.dependency_overrides[get_current_account] = lambda: None

    async def passthrough(request, call_next):
        return await call_next(request)

    # 跟正式 app 一樣：BaseHTTPMiddleware 在內，ClientDisconnectMiddleware 在最外面。
    app.middleware("http")(passthrough)
    app.add_middleware(ClientDisconnectMiddleware)
    return app


def _upstream(body) -> tuple[MagicMock, MagicMock]:
    upstream = MagicMock()
    upstream.status_code = 200
    upstream.headers = {"content-type": "text/event-stream; charset=utf-8"}
    upstream.aclose = AsyncMock(return_value=None)
    upstream.aiter_bytes = MagicMock(return_value=body)
    client = MagicMock()
    client.build_request = MagicMock(side_effect=lambda **kwargs: kwargs)
    client.send = AsyncMock(return_value=upstream)
    return upstream, client


async def _serve(app: FastAPI, *, on_body, leave: asyncio.Event) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    pending = [{"type": "http.request", "body": b'{"message":"hi"}', "more_body": False}]

    async def receive() -> dict[str, Any]:
        if pending:
            return pending.pop(0)
        await leave.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)
        if message["type"] == "http.response.body":
            on_body(message)

    scope = {
        # uvicorn 宣告的是 2.3：StreamingResponse 靠 receive 的 http.disconnect 得知斷線。
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/api/v1/chat/stream", "raw_path": b"/api/v1/chat/stream",
        "root_path": "", "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("testclient", 50000), "server": ("testserver", 80),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=5)
    return sent


def test_chat_stream_is_a_documented_route_with_chat_auth() -> None:
    routes = {
        (route.path, tuple(sorted(route.methods))): route
        for route in brain_proxy.router.routes
        if hasattr(route, "methods")
    }
    chat = routes[("/api/v1/chat", ("POST",))]
    stream = routes[("/api/v1/chat/stream", ("POST",))]
    assert [d.dependency for d in stream.dependencies] == [d.dependency for d in chat.dependencies]
    assert brain_proxy._requires_project_context("chat/stream")
    assert brain_proxy._project_access("chat/stream", "POST") is brain_proxy._project_access("chat", "POST")
    # Embed key 能用 /chat 就能用逐句版，同一份配額。
    assert is_allowlisted("POST", "/api/v1/chat/stream")


def test_each_event_is_forwarded_before_brain_sends_the_next() -> None:
    async def run() -> tuple[list[dict[str, Any]], MagicMock, dict[str, Any]]:
        first_forwarded = asyncio.Event()

        async def brain_events():
            yield _FIRST
            # Brain 還在生成：第一句沒先轉出去的話這裡會一直等，測試逾時失敗。
            await asyncio.wait_for(first_forwarded.wait(), timeout=2)
            yield _DONE

        upstream, client = _upstream(brain_events())

        def on_body(message: dict[str, Any]) -> None:
            if message.get("body") == _FIRST:
                first_forwarded.set()

        with (
            patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
            patch("app.brain_proxy._http.get", return_value=client),
        ):
            sent = await _serve(_proxy_app(), on_body=on_body, leave=asyncio.Event())
        return sent, upstream, client.build_request.call_args.kwargs

    sent, upstream, upstream_request = asyncio.run(run())

    assert upstream_request["url"] == "http://brain:8100/brain/chat/stream"
    assert upstream_request["method"] == "POST"
    start = sent[0]
    assert start["status"] == 200
    assert (b"content-type", b"text/event-stream; charset=utf-8") in start["headers"]
    bodies = [m["body"] for m in sent if m["type"] == "http.response.body" and m.get("body")]
    assert bodies == [_FIRST, _DONE]
    upstream.aclose.assert_awaited()


def test_client_leaving_mid_stream_closes_the_brain_stream() -> None:
    async def run() -> tuple[list[bytes], MagicMock, bool]:
        leave = asyncio.Event()
        brain_stopped = asyncio.Event()

        async def brain_events():
            try:
                yield _FIRST
                await asyncio.Event().wait()
                yield _DONE
            finally:
                brain_stopped.set()

        upstream, client = _upstream(brain_events())

        def on_body(message: dict[str, Any]) -> None:
            if message.get("body") == _FIRST:
                leave.set()

        with (
            patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
            patch("app.brain_proxy._http.get", return_value=client),
        ):
            sent = await _serve(_proxy_app(), on_body=on_body, leave=leave)
        bodies = [m["body"] for m in sent if m["type"] == "http.response.body" and m.get("body")]
        return bodies, upstream, brain_stopped.is_set()

    bodies, upstream, brain_stopped = asyncio.run(run())

    assert bodies == [_FIRST]
    # 關掉往 Brain 的串流，Brain 才看得到斷線、停止生成。
    upstream.aclose.assert_awaited()
    assert brain_stopped

"""Brain's copy of the client-disconnect middleware."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request

from infra import client_disconnect
from infra.client_disconnect import (
    ClientDisconnectMiddleware,
    wait_for_client_disconnect,
)

_BACKEND_COPY = Path(__file__).resolve().parents[4] / "backend" / "app" / "client_disconnect.py"


def _code_without_docstring(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = tree.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    return ast.dump(ast.Module(body=body, type_ignores=[]))


def test_matches_the_backend_copy():
    # 兩個 runtime 不共用 Python 程式碼，只能各放一份；改一邊就要改另一邊。
    if not _BACKEND_COPY.exists():
        pytest.skip("backend source is not part of this checkout")
    assert _code_without_docstring(Path(client_disconnect.__file__)) == (
        _code_without_docstring(_BACKEND_COPY)
    )


def test_chat_route_sees_disconnect_behind_base_http_middleware():
    seen: dict[str, Any] = {}
    app = FastAPI()

    @app.post("/brain/chat")
    async def chat(request: Request) -> dict[str, bool]:
        await request.body()
        try:
            await asyncio.wait_for(wait_for_client_disconnect(request), timeout=1)
            seen["disconnected"] = True
        except asyncio.TimeoutError:
            seen["disconnected"] = False
        return {"ok": True}

    async def passthrough(request, call_next):
        return await call_next(request)

    # Brain 的 metrics_middleware 是 BaseHTTPMiddleware，會吞掉斷線訊息。
    app.middleware("http")(passthrough)
    app.add_middleware(ClientDisconnectMiddleware)

    async def run() -> None:
        leave = asyncio.Event()
        pending = [{"type": "http.request", "body": b"{}", "more_body": False}]

        async def receive() -> dict[str, Any]:
            if pending:
                return pending.pop(0)
            await leave.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            return None

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "method": "POST", "scheme": "http",
            "path": "/brain/chat", "raw_path": b"/brain/chat", "root_path": "",
            "query_string": b"", "headers": [(b"content-type", b"application/json")],
            "client": ("testclient", 50000), "server": ("testserver", 80),
        }
        asyncio.get_running_loop().call_later(0.05, leave.set)
        await asyncio.wait_for(app(scope, receive, send), timeout=5)

    asyncio.run(run())

    assert seen == {"disconnected": True}


def test_brain_app_installs_the_middleware_outermost():
    import main

    assert main.app.user_middleware[0].cls is ClientDisconnectMiddleware

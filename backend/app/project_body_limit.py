"""Cap the request body of project create/delete before FastAPI parses it."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 這兩個路由只收專案名稱或專案 ID；FastAPI 解析型別化 body 前會先把整份讀進來，
# 不先限制的話，一個超大的請求要等全部讀完才會被擋。
PROJECT_BODY_MAX_BYTES = 64 * 1024
_LIMITED = {("POST", "/api/v1/projects"), ("DELETE", "/api/v1/projects")}


class ProjectBodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (scope["method"], scope["path"]) not in _LIMITED:
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > PROJECT_BODY_MAX_BYTES:
            await _too_large(scope, receive, send)
            return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > PROJECT_BODY_MAX_BYTES:
                await _too_large(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse(status_code=413, content={"detail": "request body too large"})
    await response(scope, receive, send)

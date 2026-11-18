"""Project create/delete bodies are capped before FastAPI parses them."""

from __future__ import annotations

import asyncio

from app.project_body_limit import PROJECT_BODY_MAX_BYTES, ProjectBodyLimitMiddleware


def _run(method: str, path: str, chunks: list[bytes], content_length: int | None = None):
    seen: dict[str, object] = {"called": False}
    sent: list[dict] = []
    reads = {"count": 0}

    async def app(scope, receive, send):
        seen["called"] = True
        message = await receive()
        seen["body"] = message["body"]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    queue = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]

    async def receive():
        reads["count"] += 1
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    headers = [] if content_length is None else [(b"content-length", str(content_length).encode())]
    scope = {"type": "http", "method": method, "path": path, "headers": headers}
    asyncio.run(ProjectBodyLimitMiddleware(app)(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status, seen, reads["count"]


def test_small_body_reaches_the_route_unchanged():
    status, seen, _ = _run("POST", "/api/v1/projects", [b'{"label":', b' "x"}'])
    assert status == 200
    assert seen["body"] == b'{"label": "x"}'


def test_declared_oversize_is_refused_without_reading():
    status, seen, reads = _run("POST", "/api/v1/projects", [b"x"], content_length=PROJECT_BODY_MAX_BYTES + 1)
    assert status == 413
    assert seen["called"] is False
    assert reads == 0


def test_chunked_oversize_stops_reading_at_the_cap():
    chunk = b"x" * (PROJECT_BODY_MAX_BYTES // 2 + 1)
    status, seen, reads = _run("DELETE", "/api/v1/projects", [chunk, chunk, chunk, chunk])
    assert status == 413
    assert seen["called"] is False
    assert reads == 2


def test_other_routes_are_untouched():
    big = b"x" * (PROJECT_BODY_MAX_BYTES + 10)
    status, seen, _ = _run("POST", "/api/v1/projects/abc/whatever", [big])
    assert status == 200
    assert seen["body"] == big

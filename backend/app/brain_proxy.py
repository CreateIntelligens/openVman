"""Reverse proxy: forward backend facade routes to the Brain service."""

from __future__ import annotations

from collections.abc import AsyncIterator
import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from app.config import get_tts_config

logger = logging.getLogger("backend.brain_proxy")

router = APIRouter()
_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_PUBLIC_API_PREFIX = "/api"
_INTERNAL_BRAIN_PREFIX = "/brain"
_TAG_BRAIN_SYSTEM = ["Brain"]
_TAG_TOOLS = ["Brain / Tools & Skills"]
_TAG_PROJECTS = ["Brain / Projects"]
_TAG_PERSONAS = ["Brain / Personas"]
_TAG_CHAT = ["Brain / Chat"]
_TAG_SEARCH = ["Brain / Search & Embeddings"]
_TAG_MEMORY = ["Brain / Memory & Sessions"]
_TAG_KNOWLEDGE = ["Brain / Knowledge"]
_TAG_PROTOCOL = ["Brain / Protocol"]

_BRAIN_ROUTE_DEFS = [
    {"path": f"{_PUBLIC_API_PREFIX}/health", "methods": ["GET"], "tags": _TAG_BRAIN_SYSTEM, "summary": "Brain Health"},
    {"path": f"{_PUBLIC_API_PREFIX}/metrics", "methods": ["GET"], "tags": _TAG_BRAIN_SYSTEM, "summary": "Brain Metrics"},
    {"path": f"{_PUBLIC_API_PREFIX}/identity", "methods": ["GET"], "tags": _TAG_BRAIN_SYSTEM, "summary": "Brain Identity"},
    {"path": f"{_PUBLIC_API_PREFIX}/tools", "methods": ["GET"], "tags": _TAG_TOOLS, "summary": "List Tools"},
    {"path": f"{_PUBLIC_API_PREFIX}/skills/{{skill_id}}/toggle", "methods": ["PATCH"], "tags": _TAG_TOOLS, "summary": "Toggle Skill"},
    {"path": f"{_PUBLIC_API_PREFIX}/skills", "methods": ["POST"], "tags": _TAG_TOOLS, "summary": "Create Skill"},
    {"path": f"{_PUBLIC_API_PREFIX}/skills/{{skill_id}}/files", "methods": ["GET"], "tags": _TAG_TOOLS, "summary": "Get Skill Files"},
    {"path": f"{_PUBLIC_API_PREFIX}/skills/{{skill_id}}/files", "methods": ["PUT"], "tags": _TAG_TOOLS, "summary": "Update Skill Files"},
    {"path": f"{_PUBLIC_API_PREFIX}/skills/{{skill_id}}", "methods": ["DELETE"], "tags": _TAG_TOOLS, "summary": "Delete Skill"},
    {"path": f"{_PUBLIC_API_PREFIX}/skills/reload", "methods": ["POST"], "tags": _TAG_TOOLS, "summary": "Reload Skills"},
    {"path": f"{_PUBLIC_API_PREFIX}/projects", "methods": ["GET"], "tags": _TAG_PROJECTS, "summary": "List Projects"},
    {"path": f"{_PUBLIC_API_PREFIX}/projects", "methods": ["POST"], "tags": _TAG_PROJECTS, "summary": "Create Project"},
    {"path": f"{_PUBLIC_API_PREFIX}/projects", "methods": ["DELETE"], "tags": _TAG_PROJECTS, "summary": "Delete Project"},
    {"path": f"{_PUBLIC_API_PREFIX}/projects/{{project_id}}", "methods": ["GET"], "tags": _TAG_PROJECTS, "summary": "Get Project"},
    {"path": f"{_PUBLIC_API_PREFIX}/personas", "methods": ["GET"], "tags": _TAG_PERSONAS, "summary": "List Personas"},
    {"path": f"{_PUBLIC_API_PREFIX}/personas", "methods": ["POST"], "tags": _TAG_PERSONAS, "summary": "Create Persona"},
    {"path": f"{_PUBLIC_API_PREFIX}/personas", "methods": ["DELETE"], "tags": _TAG_PERSONAS, "summary": "Delete Persona"},
    {"path": f"{_PUBLIC_API_PREFIX}/personas/clone", "methods": ["POST"], "tags": _TAG_PERSONAS, "summary": "Clone Persona"},
    {"path": f"{_PUBLIC_API_PREFIX}/chat", "methods": ["POST"], "tags": _TAG_CHAT, "summary": "Chat"},
    {"path": f"{_PUBLIC_API_PREFIX}/chat/stream", "methods": ["POST"], "tags": _TAG_CHAT, "summary": "Chat Stream"},
    {"path": f"{_PUBLIC_API_PREFIX}/chat/history", "methods": ["GET"], "tags": _TAG_CHAT, "summary": "Chat History"},
    {"path": f"{_PUBLIC_API_PREFIX}/embed", "methods": ["POST"], "tags": _TAG_SEARCH, "summary": "Embed Text"},
    {"path": f"{_PUBLIC_API_PREFIX}/search", "methods": ["POST"], "tags": _TAG_SEARCH, "summary": "Search"},
    {"path": f"{_PUBLIC_API_PREFIX}/memories", "methods": ["POST"], "tags": _TAG_MEMORY, "summary": "Add Memory"},
    {"path": f"{_PUBLIC_API_PREFIX}/memories", "methods": ["GET"], "tags": _TAG_MEMORY, "summary": "List Memories"},
    {"path": f"{_PUBLIC_API_PREFIX}/memories", "methods": ["DELETE"], "tags": _TAG_MEMORY, "summary": "Delete Memory"},
    {"path": f"{_PUBLIC_API_PREFIX}/memories/maintain", "methods": ["POST"], "tags": _TAG_MEMORY, "summary": "Maintain Memories"},
    {"path": f"{_PUBLIC_API_PREFIX}/sessions", "methods": ["GET"], "tags": _TAG_MEMORY, "summary": "List Sessions"},
    {"path": f"{_PUBLIC_API_PREFIX}/sessions/{{session_id}}", "methods": ["DELETE"], "tags": _TAG_MEMORY, "summary": "Delete Session"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/documents", "methods": ["GET"], "tags": _TAG_KNOWLEDGE, "summary": "List Knowledge Documents"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/base/documents", "methods": ["GET"], "tags": _TAG_KNOWLEDGE, "summary": "List Base Knowledge Documents"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/document", "methods": ["GET"], "tags": _TAG_KNOWLEDGE, "summary": "Get Knowledge Document"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/document", "methods": ["PUT"], "tags": _TAG_KNOWLEDGE, "summary": "Save Knowledge Document"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/document", "methods": ["DELETE"], "tags": _TAG_KNOWLEDGE, "summary": "Delete Knowledge Document"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/move", "methods": ["POST"], "tags": _TAG_KNOWLEDGE, "summary": "Move Knowledge Document"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/directory", "methods": ["POST"], "tags": _TAG_KNOWLEDGE, "summary": "Create Knowledge Directory"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/directory", "methods": ["DELETE"], "tags": _TAG_KNOWLEDGE, "summary": "Delete Knowledge Directory"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/upload", "methods": ["POST"], "tags": _TAG_KNOWLEDGE, "summary": "Upload Knowledge Documents"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/reindex", "methods": ["POST"], "tags": _TAG_KNOWLEDGE, "summary": "Reindex Knowledge"},
    {"path": f"{_PUBLIC_API_PREFIX}/protocol/validate", "methods": ["POST"], "tags": _TAG_PROTOCOL, "summary": "Validate Protocol Event"},
]

# Headers that must not be forwarded (hop-by-hop / causes conflicts).
_HOP_BY_HOP = frozenset({
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "upgrade",
    "proxy-authorization",
    "proxy-authenticate",
    "te",
    "trailers",
})

# Shared client – created lazily so the event loop is available.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=120, write=30, pool=10),
            follow_redirects=False,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _filter_headers(headers: httpx.Headers | dict) -> dict[str, str]:
    return {
        k: v
        for k, v in headers.items()
        if k.lower() not in _HOP_BY_HOP
    }


def _target_url(path: str, query: str) -> str:
    cfg = get_tts_config()
    target_url = f"{cfg.brain_url}{_INTERNAL_BRAIN_PREFIX}/{path}"
    if query:
        return f"{target_url}?{query}"
    return target_url


async def _stream_upstream_bytes(upstream: httpx.Response) -> AsyncIterator[bytes]:
    try:
        async for chunk in upstream.aiter_bytes():
            yield chunk
    finally:
        await upstream.aclose()


async def _proxy_to_brain(request: Request, path: str) -> Response:
    headers = _filter_headers(request.headers)
    body = await request.body()
    client = _get_client()

    try:
        upstream = await client.send(
            client.build_request(
                method=request.method,
                url=_target_url(path, request.url.query),
                headers=headers,
                content=body,
            ),
            stream=True,
        )
    except httpx.ConnectError:
        logger.warning("brain unreachable at %s", get_tts_config().brain_url)
        return JSONResponse(
            content={"error": "brain service unavailable"},
            status_code=502,
        )

    content_type = upstream.headers.get("content-type", "")
    resp_headers = _filter_headers(upstream.headers)

    # SSE / streaming responses — forward chunks via StreamingResponse.
    if "text/event-stream" in content_type:
        return StreamingResponse(
            _stream_upstream_bytes(upstream),
            status_code=upstream.status_code,
            media_type="text/event-stream",
            headers=resp_headers,
        )

    # Non-streaming: read full body, close stream, return plain Response.
    content = await upstream.aread()
    await upstream.aclose()

    return Response(
        content=content,
        status_code=upstream.status_code,
        media_type=content_type or "application/json",
        headers=resp_headers,
    )


def _request_brain_path(request: Request) -> str:
    return request.url.path.removeprefix(f"{_PUBLIC_API_PREFIX}/").lstrip("/")


async def documented_brain_proxy(request: Request) -> Response:
    return await _proxy_to_brain(request, _request_brain_path(request))


for route_def in _BRAIN_ROUTE_DEFS:
    router.add_api_route(
        route_def["path"],
        documented_brain_proxy,
        methods=route_def["methods"],
        tags=route_def["tags"],
        summary=route_def["summary"],
        name=f"mirror_{route_def['methods'][0].lower()}_{route_def['path']}",
    )


@router.api_route(
    "/api/{path:path}",
    methods=_PROXY_METHODS,
    include_in_schema=False,
)
async def brain_proxy(request: Request, path: str) -> Response:
    return await _proxy_to_brain(request, path)

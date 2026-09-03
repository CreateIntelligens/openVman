"""Reverse proxy: forward backend facade routes to the Brain service."""

from __future__ import annotations

from collections.abc import AsyncIterator
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from app.auth.dependencies import (
    CurrentAccount,
    authenticate_request,
    get_current_account,
)
from app.auth.embed import enforce_project_binding
from app.auth.models import ResourceType
from app.auth.resources import (
    ResourceAccess,
    ResourceNotFoundError,
    resolve_resource,
)
from app.auth.runtime import get_auth_runtime
from app.config import get_tts_config
from app.http_client import SharedAsyncClient

logger = logging.getLogger("backend.brain_proxy")

router = APIRouter()
_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_PUBLIC_API_PREFIX = "/api/v1"
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
_PUBLIC_BRAIN_PATHS = frozenset({f"{_PUBLIC_API_PREFIX}/health"})

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
    {"path": f"{_PUBLIC_API_PREFIX}/personas/avatar", "methods": ["POST"], "tags": _TAG_PERSONAS, "summary": "Bind Persona Avatar"},
    {"path": f"{_PUBLIC_API_PREFIX}/chat", "methods": ["POST"], "tags": _TAG_CHAT, "summary": "Chat"},
    {"path": f"{_PUBLIC_API_PREFIX}/chat/history", "methods": ["GET"], "tags": _TAG_CHAT, "summary": "Chat History"},
    {"path": f"{_PUBLIC_API_PREFIX}/embed", "methods": ["POST"], "tags": _TAG_SEARCH, "summary": "Embed Text"},
    {"path": f"{_PUBLIC_API_PREFIX}/search", "methods": ["POST"], "tags": _TAG_SEARCH, "summary": "Search"},
    {"path": f"{_PUBLIC_API_PREFIX}/memories", "methods": ["POST"], "tags": _TAG_MEMORY, "summary": "Add Memory"},
    {"path": f"{_PUBLIC_API_PREFIX}/memories", "methods": ["GET"], "tags": _TAG_MEMORY, "summary": "List Memories"},
    {"path": f"{_PUBLIC_API_PREFIX}/memories", "methods": ["DELETE"], "tags": _TAG_MEMORY, "summary": "Delete Memory"},
    {"path": f"{_PUBLIC_API_PREFIX}/memories/maintain", "methods": ["POST"], "tags": _TAG_MEMORY, "summary": "Maintain Memories"},
    {"path": f"{_PUBLIC_API_PREFIX}/sessions", "methods": ["GET"], "tags": _TAG_MEMORY, "summary": "List Sessions"},
    {"path": f"{_PUBLIC_API_PREFIX}/sessions/export", "methods": ["GET"], "tags": _TAG_MEMORY, "summary": "Export Sessions"},
    {"path": f"{_PUBLIC_API_PREFIX}/sessions/{{session_id}}", "methods": ["DELETE"], "tags": _TAG_MEMORY, "summary": "Delete Session"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/documents", "methods": ["GET"], "tags": _TAG_KNOWLEDGE, "summary": "List Knowledge Documents"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/base/documents", "methods": ["GET"], "tags": _TAG_KNOWLEDGE, "summary": "List Base Knowledge Documents"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/document", "methods": ["GET"], "tags": _TAG_KNOWLEDGE, "summary": "Get Knowledge Document"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/document", "methods": ["PUT"], "tags": _TAG_KNOWLEDGE, "summary": "Save Knowledge Document"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/document/meta", "methods": ["PATCH"], "tags": _TAG_KNOWLEDGE, "summary": "Update Knowledge Document Metadata"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/document", "methods": ["DELETE"], "tags": _TAG_KNOWLEDGE, "summary": "Delete Knowledge Document"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/move", "methods": ["POST"], "tags": _TAG_KNOWLEDGE, "summary": "Move Knowledge Document"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/directory", "methods": ["POST"], "tags": _TAG_KNOWLEDGE, "summary": "Create Knowledge Directory"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/directory", "methods": ["DELETE"], "tags": _TAG_KNOWLEDGE, "summary": "Delete Knowledge Directory"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/note", "methods": ["POST"], "tags": _TAG_KNOWLEDGE, "summary": "Create Knowledge Note"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/reindex", "methods": ["POST"], "tags": _TAG_KNOWLEDGE, "summary": "Reindex Knowledge"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/graph/rebuild", "methods": ["POST"], "tags": _TAG_KNOWLEDGE, "summary": "Rebuild Knowledge Graph"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/graph/status", "methods": ["GET"], "tags": _TAG_KNOWLEDGE, "summary": "Get Knowledge Graph Status"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/graph/summary", "methods": ["GET"], "tags": _TAG_KNOWLEDGE, "summary": "Get Knowledge Graph Summary"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/graph", "methods": ["GET"], "tags": _TAG_KNOWLEDGE, "summary": "Get Knowledge Graph JSON"},
    {"path": f"{_PUBLIC_API_PREFIX}/knowledge/graph/html", "methods": ["GET"], "tags": _TAG_KNOWLEDGE, "summary": "Get Knowledge Graph HTML"},
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
# 這幾個 header 由本層的 ASGI server 自行產生；把上游那份一併轉發會讓
# 回應出現重複的 date/server，nginx 會警告並丟棄後者。
_SERVER_GENERATED_HEADERS = frozenset({"date", "server"})
_INTERNAL_TOKEN_HEADER = "X-Internal-Token"
_OPENVMAN_HEADER_PREFIX = "x-openvman-"
_USER_ID_HEADER = "X-OpenVMan-User-ID"
_USER_ROLE_HEADER = "X-OpenVMan-Role"
_PROJECT_ID_HEADER = "X-OpenVMan-Project-ID"
_PRINCIPAL_TYPE_HEADER = "X-Principal-Type"
_PRINCIPAL_ID_HEADER = "X-Principal-Id"
_PRINCIPAL_HEADERS = frozenset(
    {_PRINCIPAL_TYPE_HEADER.lower(), _PRINCIPAL_ID_HEADER.lower()}
)
_EMBED_PRINCIPAL_TYPE = "embed_key"
_SESSION_PRINCIPAL_TYPE = "user"
_END_USER_AUTH_HEADERS = frozenset({"authorization", "cookie"})
_PROJECT_SCOPED_PREFIXES = (
    "chat",
    "embed",
    "health",
    "identity",
    "knowledge",
    "memories",
    "personas",
    "search",
    "sessions",
    "skills",
    "tools",
    "dreaming",
)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# 這些 Brain 路徑由 Backend 自己的路由（含帳號範圍限制）對外提供，
# catch-all 直通會繞過那層限制，所以一律擋掉。
_BACKEND_OWNED_PREFIXES = ("usage",)

_http = SharedAsyncClient(connect=10, read=120, write=30, pool=10)


def _filter_headers(headers: httpx.Headers | dict | Any) -> dict[str, str]:
    return {
        k: v
        for k, v in headers.items()
        if k.lower() not in _HOP_BY_HOP
        and k.lower() not in _SERVER_GENERATED_HEADERS
    }


def _filter_external_request_headers(
    headers: httpx.Headers | dict | Any,
) -> dict[str, str]:
    """Remove transport and caller-controlled service identity headers."""
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in _HOP_BY_HOP
        and key.lower() not in _END_USER_AUTH_HEADERS
        and key.lower() != _INTERNAL_TOKEN_HEADER.lower()
        and not key.lower().startswith(_OPENVMAN_HEADER_PREFIX)
        # 主體標頭只由這一層產生；照抄上游帶進來的那份等於讓呼叫端
        # 自稱是任意 embed key。
        and key.lower() not in _PRINCIPAL_HEADERS
    }


def _resolved_project_id(request: Request) -> str | None:
    project_id = getattr(request.state, "resolved_project_id", None)
    if not isinstance(project_id, str):
        return None
    project_id = project_id.strip()
    return project_id or None


async def _request_project_id(request: Request) -> str | None:
    candidates: list[str] = []
    query_project_id = request.query_params.get("project_id", "").strip()
    if query_project_id:
        candidates.append(query_project_id)

    content_type = request.headers.get("content-type", "").casefold()
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except (UnicodeDecodeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            body_project_id = payload.get("project_id")
            if isinstance(body_project_id, str) and body_project_id.strip():
                candidates.append(body_project_id.strip())

    if not candidates:
        return None
    if len(set(candidates)) != 1:
        raise ResourceNotFoundError
    return candidates[0]


def _requires_project_context(path: str) -> bool:
    normalized = path.strip("/")
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in _PROJECT_SCOPED_PREFIXES
    )


def _project_access(path: str, method: str) -> ResourceAccess:
    normalized = path.strip("/")
    if normalized == "sessions/export":
        return ResourceAccess.EDIT
    if method.upper() in _SAFE_METHODS:
        return ResourceAccess.READ
    project_area = normalized.partition("/")[0]
    if project_area in {"knowledge", "personas", "skills", "tools", "dreaming"}:
        return ResourceAccess.EDIT
    if project_area == "sessions":
        return ResourceAccess.EDIT
    if project_area == "memories":
        return ResourceAccess.EDIT
    return ResourceAccess.READ


async def _authorize_project_context(
    request: Request,
    path: str,
    current: CurrentAccount | None,
    explicit_project_id: str | None,
) -> str | None:
    if current is None or not _requires_project_context(path):
        return explicit_project_id

    if current.embed_key is not None:
        # Embed key 沒有資源授權，專案由金鑰本身綁定；client 自帶不同的
        # project_id 一律 403，不能靜默改用金鑰的專案。
        enforce_project_binding(
            current.embed_key,
            await _request_project_id(request) or "",
        )
        request.state.resolved_project_id = current.embed_key.project_id
        return current.embed_key.project_id

    supplied_project_id = await _request_project_id(request)
    resolved_project_id = explicit_project_id or supplied_project_id
    if (
        explicit_project_id is not None
        and supplied_project_id is not None
        and supplied_project_id != explicit_project_id
    ):
        raise ResourceNotFoundError
    if resolved_project_id is None:
        raise ResourceNotFoundError

    runtime = get_auth_runtime()
    resolve_resource(
        runtime.resources,
        current.user,
        ResourceType.PROJECT,
        resolved_project_id,
        access=_project_access(path, request.method),
    )
    request.state.resolved_project_id = resolved_project_id
    return resolved_project_id


def _trusted_upstream_headers(
    request: Request,
    *,
    current: CurrentAccount | None,
    project_id: str | None,
) -> dict[str, str]:
    headers = _filter_external_request_headers(request.headers)
    headers[_INTERNAL_TOKEN_HEADER] = get_tts_config().gateway_internal_token
    if current is None:
        return headers

    headers[_USER_ID_HEADER] = current.user.id
    headers[_USER_ROLE_HEADER] = current.user.role.value
    if current.embed_key is not None:
        headers[_PRINCIPAL_TYPE_HEADER] = _EMBED_PRINCIPAL_TYPE
        headers[_PRINCIPAL_ID_HEADER] = current.embed_key.key_id
    else:
        headers[_PRINCIPAL_TYPE_HEADER] = _SESSION_PRINCIPAL_TYPE
        headers[_PRINCIPAL_ID_HEADER] = current.user.id
    resolved_project_id = project_id or _resolved_project_id(request)
    if resolved_project_id:
        headers[_PROJECT_ID_HEADER] = resolved_project_id
    return headers


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


async def proxy_to_brain(
    request: Request,
    path: str,
    *,
    current: CurrentAccount | None,
    project_id: str | None = None,
) -> Response:
    """Forward a request with identity supplied only by trusted Backend state."""
    normalized_path = path.strip("/")
    if any(
        normalized_path == prefix or normalized_path.startswith(f"{prefix}/")
        for prefix in _BACKEND_OWNED_PREFIXES
    ):
        return JSONResponse(status_code=404, content={"detail": "Resource not found"})
    try:
        project_id = await _authorize_project_context(
            request,
            path,
            current,
            project_id,
        )
    except ResourceNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"detail": "Resource not found"},
        )
    headers = _trusted_upstream_headers(
        request,
        current=current,
        project_id=project_id,
    )
    body = await request.body()
    client = _http.get()

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
        try:
            content = await upstream.aread()
        finally:
            await upstream.aclose()

        return Response(
            content=content,
            status_code=upstream.status_code,
            media_type=content_type or "application/json",
            headers=resp_headers,
        )
    except httpx.TimeoutException as exc:
        logger.warning("brain request timeout path=%s error=%s", path, exc)
        return JSONResponse(
            content={"error": "brain request timeout"},
            status_code=504,
        )
    except httpx.ConnectError:
        logger.warning("brain unreachable at %s", get_tts_config().brain_url)
        return JSONResponse(
            content={"error": "brain service unavailable"},
            status_code=502,
        )
    except httpx.RemoteProtocolError as exc:
        logger.warning("brain upstream disconnected path=%s error=%s", path, exc)
        return JSONResponse(
            content={"error": "brain upstream disconnected"},
            status_code=502,
        )
    except httpx.ReadError as exc:
        logger.warning("brain upstream read error path=%s error=%s", path, exc)
        return JSONResponse(
            content={"error": "brain upstream read error"},
            status_code=502,
        )
    except httpx.RequestError as exc:
        logger.warning("brain request error path=%s error=%s", path, exc)
        return JSONResponse(
            content={"error": "brain request error"},
            status_code=502,
        )


async def _proxy_to_brain(request: Request, path: str) -> Response:
    """Compatibility wrapper for existing facade callers and tests."""
    current = getattr(request.state, "current_account", None)
    if not isinstance(current, CurrentAccount):
        current = None
    return await proxy_to_brain(request, path, current=current)


def _request_brain_path(request: Request) -> str:
    return request.url.path.removeprefix(f"{_PUBLIC_API_PREFIX}/").lstrip("/")


def _catchall_current_account(request: Request) -> CurrentAccount | None:
    if request.url.path in _PUBLIC_BRAIN_PATHS:
        return None
    existing = getattr(request.state, "current_account", None)
    if isinstance(existing, CurrentAccount):
        return existing
    return authenticate_request(request, get_auth_runtime())


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
        dependencies=(
            []
            if route_def["path"] in _PUBLIC_BRAIN_PATHS
            else [Depends(get_current_account)]
        ),
    )


@router.api_route(
    "/api/v1/{path:path}",
    methods=_PROXY_METHODS,
    include_in_schema=False,
)
async def brain_proxy(
    request: Request,
    path: str,
    _current: CurrentAccount | None = Depends(_catchall_current_account),
) -> Response:
    return await _proxy_to_brain(request, path)

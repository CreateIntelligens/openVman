"""Reverse proxy: forward backend facade routes to the Brain service."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable
from time import monotonic
from typing import Any, TypeVar
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from app.ai_cleanup_guard import AiCleanupRefused, guard_ai_cleanup
from app.auth import brain_project_access
from app.auth.dependencies import (
    CurrentAccount,
    authenticate_request,
    get_current_account,
)
from app.auth.policy import is_vendor_account
from app.auth.resources import ResourceNotFoundError
from app.auth.runtime import get_auth_runtime
from app.auth.vendor_access import (
    KNOWLEDGE_DOCUMENT_ROUTES,
    VENDOR_HEADER,
    is_vendor_knowledge_path,
    vendor_route_allowed,
)
from app.chat_tts_text import (
    TTS_TEXT_PATHS,
    TTS_TEXT_STREAM_PATHS,
    annotate_json_body,
    annotate_sse,
)
from app.client_disconnect import wait_for_client_disconnect
from app.config import get_tts_config
from app.http_client import SharedAsyncClient
from app.skill_write_guard import (
    is_skill_toggle,
    is_skill_write,
    skill_request_refusal,
)
from app.upstream_guard import (
    ERROR,
    OK,
    REQUEST_ID_HEADER,
    classify_outcome,
    current_request_id,
    describe_error,
    emit_attempt,
    host_of,
    knob,
)
from app.utils.log_safe import log_safe

logger = logging.getLogger("backend.brain_proxy")

router = APIRouter()
_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_PUBLIC_API_PREFIX = "/api/v1"
_INTERNAL_BRAIN_PREFIX = "/brain"
_TAG_BRAIN_SYSTEM = ["Brain"]
_TAG_TOOLS = ["Brain / Tools & Skills"]
_TAG_PERSONAS = ["Brain / Personas"]
_TAG_CHAT = ["Brain / Chat"]
_TAG_SEARCH = ["Brain / Search & Embeddings"]
_TAG_MEMORY = ["Brain / Memory & Sessions"]
_TAG_KNOWLEDGE = ["Brain / Knowledge"]
_TAG_PROTOCOL = ["Brain / Protocol"]
_PUBLIC_BRAIN_PATHS = frozenset({f"{_PUBLIC_API_PREFIX}/health"})
_CHAT_PATHS = frozenset({f"{_PUBLIC_API_PREFIX}/chat", f"{_PUBLIC_API_PREFIX}/chat/stream"})


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
    {"path": f"{_PUBLIC_API_PREFIX}/personas/soul", "methods": ["GET"], "tags": _TAG_PERSONAS, "summary": "Read persona SOUL.md"},
    {"path": f"{_PUBLIC_API_PREFIX}/personas/soul", "methods": ["PUT"], "tags": _TAG_PERSONAS, "summary": "Save persona SOUL.md"},
    {"path": f"{_PUBLIC_API_PREFIX}/personas/agents", "methods": ["GET"], "tags": _TAG_PERSONAS, "summary": "Read persona AGENTS.md"},
    {"path": f"{_PUBLIC_API_PREFIX}/personas/agents", "methods": ["PUT"], "tags": _TAG_PERSONAS, "summary": "Save persona AGENTS.md"},
    {"path": f"{_PUBLIC_API_PREFIX}/personas/guardrails", "methods": ["GET"], "tags": _TAG_PERSONAS, "summary": "Read project guardrails"},
    {"path": f"{_PUBLIC_API_PREFIX}/personas", "methods": ["GET"], "tags": _TAG_PERSONAS, "summary": "List Personas"},
    {"path": f"{_PUBLIC_API_PREFIX}/personas", "methods": ["POST"], "tags": _TAG_PERSONAS, "summary": "Create Persona"},
    {"path": f"{_PUBLIC_API_PREFIX}/personas", "methods": ["DELETE"], "tags": _TAG_PERSONAS, "summary": "Delete Persona"},
    {"path": f"{_PUBLIC_API_PREFIX}/personas/clone", "methods": ["POST"], "tags": _TAG_PERSONAS, "summary": "Clone Persona"},
    {"path": f"{_PUBLIC_API_PREFIX}/personas/avatar", "methods": ["POST"], "tags": _TAG_PERSONAS, "summary": "Bind Persona Avatar"},
    {"path": f"{_PUBLIC_API_PREFIX}/chat", "methods": ["POST"], "tags": _TAG_CHAT, "summary": "Chat"},
    {"path": f"{_PUBLIC_API_PREFIX}/chat/stream", "methods": ["POST"], "tags": _TAG_CHAT, "summary": "Chat (SSE sentence stream)", "response_class": "event_stream"},
    {"path": f"{_PUBLIC_API_PREFIX}/chat/accept", "methods": ["POST"], "tags": _TAG_CHAT, "summary": "Accept Chat Turn"},
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
    {"path": f"{_PUBLIC_API_PREFIX}/sessions/batch-delete", "methods": ["POST"], "tags": _TAG_MEMORY, "summary": "Batch Delete Sessions"},
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
    {"path": f"{_PUBLIC_API_PREFIX}/{brain_project_access.PROJECT_FEATURES_PATH}", "methods": ["PATCH"], "tags": _TAG_KNOWLEDGE, "summary": "Update Project Memory and Graph Features"},
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
_BRAIN_HEADER_PREFIX = "x-brain-"
_USER_ID_HEADER = "X-OpenVMan-User-ID"
_USER_ROLE_HEADER = "X-OpenVMan-Role"
_PROJECT_ID_HEADER = "X-OpenVMan-Project-ID"
_PROJECT_WRITES_HEADER = "X-OpenVMan-Project-Writes"
_PRINCIPAL_TYPE_HEADER = "X-Principal-Type"
_PRINCIPAL_ID_HEADER = "X-Principal-Id"
_PRINCIPAL_HEADERS = frozenset(
    {_PRINCIPAL_TYPE_HEADER.lower(), _PRINCIPAL_ID_HEADER.lower()}
)
_EMBED_PRINCIPAL_TYPE = "embed_key"
_API_KEY_PRINCIPAL_TYPE = "api_key"
_SESSION_PRINCIPAL_TYPE = "user"
_END_USER_AUTH_HEADERS = frozenset({"authorization", "cookie"})
# 這些 Brain 路徑由 Backend 自己的路由（含帳號範圍限制）對外提供，
# catch-all 直通會繞過那層限制，所以一律擋掉。
_BACKEND_OWNED_PREFIXES = (
    # 備份限 ROOT，由 routes/admin.py 轉發；catch-all 不得讓一般帳號直通。
    "backups",
    # Brain 的 internal 路由（斷路器重置、金鑰指紋、設定刷新）只給 Backend 自己的
    # 路由在伺服器端呼叫；catch-all 帶著 internal token 直通會讓任何登入帳號碰到。
    "internal",
    "knowledge/raw/upload",
    "knowledge/upload",
    "usage",
)

def _brain_http_timeout() -> httpx.Timeout:
    # Brain 在同一個 docker 網路：連不上 2 秒就夠判斷；read 是兩個 chunk 之間的上限，
    # LLM 跑工具時一句話之間可能停很久，維持 120 秒。
    # pool 是等空連線的時間，跟 Brain 連不連得上無關：瞬間 200 人時連線池排隊，
    # 用 connect 的 2 秒會把還在排隊的請求直接回 504。
    cfg = get_tts_config()
    return httpx.Timeout(
        connect=knob(cfg, "brain_proxy_connect_timeout_seconds"),
        read=knob(cfg, "brain_proxy_read_timeout_seconds"),
        write=30,
        pool=30,
    )


# 每段對話串流佔一條連線、一直開到回答結束；httpx 預設上限 100 條，
# 單一 Backend process 同時超過 100 段對話就排隊（2026-11-13 隔離壓測瞬間 200 人
# 有 23～49% 回 504）。
_BRAIN_LIMITS = httpx.Limits(max_connections=1000, max_keepalive_connections=200)

_http = SharedAsyncClient(timeout_factory=_brain_http_timeout, limits=_BRAIN_LIMITS)


class _EventStreamResponse(StreamingResponse):
    """Documents the SSE media type; the proxy returns Brain's stream as-is."""

    media_type = "text/event-stream"


_EVENT_STREAM_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": (
            "text/event-stream。`sentence` 事件逐句帶 `{index, text}`；"
            "`done` 帶與 `/api/v1/chat` 相同的完整回應（欄位見 ChatResponse）；"
            "`error` 帶 `{status, detail}`。收到 `done` 或 `error` 後串流結束。"
        ),
    },
}
_CHAT_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "description": (
            "內容被拒：空訊息、超過長度上限或內容檢查擋下。detail 為 "
            "`{event: \"server_error\", error_code: \"INVALID_REQUEST\", message}`；"
            "session 已達輪數上限時 error_code 為 SESSION_EXPIRED。改內容或換新的 "
            "session_id 再送，不必當成服務故障。`chat/stream` 在串流中以 `error` 事件"
            "帶同樣的 `{status, detail}`"
        ),
    },
    429: {
        "description": (
            "請求太頻繁：帳號 API key 每分鐘上限（API_KEY_RATE_LIMIT_PER_MINUTE，預設 300），"
            "或同一呼叫者在同一專案的對話每分鐘上限（預設 90，detail.error_code 為 "
            "LLM_OVERLOAD）。依 Retry-After 秒數後重試"
        ),
        "headers": {
            "Retry-After": {
                "description": "距離可再呼叫的秒數",
                "schema": {"type": "integer"},
            },
        },
    },
}
_PROJECT_CONTEXT_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"description": "專案不存在或沒有權限"},
    422: {
        "description": (
            "沒帶 project_id（query 或 JSON body 擇一），或 query 與 body 的 "
            "project_id 不一致；在其他欄位驗證之前回應。"
            "Embed key 由金鑰綁定專案，可省略。"
        ),
    },
}

# nginx 的慣例：用戶端先斷線、伺服器沒回應。對方已經不在，這個狀態碼只會進 log。
CLIENT_CLOSED_REQUEST = 499

_T = TypeVar("_T")


class _ClientDisconnected(Exception):
    """The caller hung up while Backend was still waiting on Brain."""


async def _unless_client_gone(request: Request, work: Awaitable[_T]) -> _T:
    """Await *work*, cancelling it as soon as the caller disconnects.

    取消 httpx 的 send 會關掉往 Brain 的連線，Brain 看到斷線就停止生成；
    不這樣做的話使用者打斷數位人後，Brain 仍把整輪 LLM 與工具跑完。
    正常請求在 work 完成的當下就返回，不多等。
    """
    work_task = asyncio.ensure_future(work)
    watch_task = asyncio.ensure_future(wait_for_client_disconnect(request))
    try:
        done, _ = await asyncio.wait(
            {work_task, watch_task}, return_when=asyncio.FIRST_COMPLETED,
        )
        if work_task in done:
            return work_task.result()
        work_task.cancel()
        await asyncio.wait({work_task})
        # 取消前一刻剛好拿到回應時要把它關掉，連線才會還回連線池。
        if not work_task.cancelled() and work_task.exception() is None:
            late = work_task.result()
            if isinstance(late, httpx.Response):
                await late.aclose()
        raise _ClientDisconnected
    finally:
        watch_task.cancel()
        if not work_task.done():
            work_task.cancel()


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
        # Brain 會把 X-Brain-Project／X-Brain-Channel 當成專案與通道的備援來源；
        # 專案只能由這一層授權後決定，呼叫端帶的一律不轉。
        and not key.lower().startswith(_BRAIN_HEADER_PREFIX)
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


def _trusted_upstream_headers(
    request: Request,
    *,
    current: CurrentAccount | None,
    project_id: str | None,
) -> dict[str, str]:
    headers = _filter_external_request_headers(request.headers)
    headers[_INTERNAL_TOKEN_HEADER] = get_tts_config().gateway_internal_token
    if request_id := current_request_id():
        # 同一個 id 帶到 Brain，兩邊的 log 才串得起來。
        headers[REQUEST_ID_HEADER] = request_id
    if current is None:
        return headers

    headers[_USER_ID_HEADER] = current.user.id
    headers[_USER_ROLE_HEADER] = current.user.role.value
    if current.embed_key is not None:
        headers[_PRINCIPAL_TYPE_HEADER] = _EMBED_PRINCIPAL_TYPE
        headers[_PRINCIPAL_ID_HEADER] = current.embed_key.key_id
    elif current.api_key is not None:
        headers[_PRINCIPAL_TYPE_HEADER] = _API_KEY_PRINCIPAL_TYPE
        headers[_PRINCIPAL_ID_HEADER] = current.api_key.key_id
    else:
        headers[_PRINCIPAL_TYPE_HEADER] = _SESSION_PRINCIPAL_TYPE
        headers[_PRINCIPAL_ID_HEADER] = current.user.id
    resolved_project_id = project_id or _resolved_project_id(request)
    if resolved_project_id:
        headers[_PROJECT_ID_HEADER] = resolved_project_id
    return headers


def _brain_base_url(path: str, method: str) -> str:
    cfg = get_tts_config()
    chat_methods = {
        "chat": "POST",
        "chat/stream": "POST",
        "chat/accept": "POST",
        "chat/history": "GET",
        "chat/modes": "GET",
        "search": "POST",
    }
    if chat_methods.get(path.strip("/")) == method.upper():
        return cfg.resolved_brain_chat_url.rstrip("/")
    return cfg.brain_url.rstrip("/")


def _target_url(path: str, query: str, method: str = "GET") -> str:
    # path 是解碼過一次、拿來做所有授權判斷的那一份。原樣接進網址的話，殘留的
    # %xx（例如 %73kills）、? 與 # 會被 Brain 再解讀一次，變成另一條路徑或另一組
    # query；重新編碼後 Brain 解碼一次，拿到的就是這裡授權的同一個字串。
    target_url = (
        f"{_brain_base_url(path, method)}{_INTERNAL_BRAIN_PREFIX}/"
        f"{quote(path, safe='/')}"
    )
    if query:
        return f"{target_url}?{query}"
    return target_url


def _brain_host(path: str = "", method: str = "GET") -> str:
    return host_of(_brain_base_url(path, method))


async def _stream_upstream_bytes(
    upstream: httpx.Response,
    *,
    path: str = "",
    started: float | None = None,
    sse: bool = False,
    method: str = "GET",
) -> AsyncIterator[bytes]:
    """Relay Brain's stream; a mid-stream timeout ends it with an SSE ``error`` event.

    header 已經送出，沒辦法再改成 504；SSE 就補一個跟 Brain 同格式的 error 事件，
    前台照一般錯誤處理，不會卡在等下一句。
    """
    started = monotonic() if started is None else started
    outcome, error, tail = OK, "", b"\n\n"
    try:
        async for chunk in upstream.aiter_bytes():
            if chunk:
                tail = chunk[-2:]
            yield chunk
    except httpx.HTTPError as exc:
        outcome, error = classify_outcome(exc)
        logger.warning(
            "brain stream interrupted path=%s error=%s",
            log_safe(path), log_safe(error),
        )
        if sse:
            status = 504 if outcome.startswith("timeout") else 502
            body = json.dumps({"status": status, "detail": f"brain stream interrupted: {outcome}"})
            prefix = b"" if tail.endswith(b"\n\n") else b"\n\n"
            yield prefix + f"event: error\ndata: {body}\n\n".encode()
    finally:
        emit_attempt(
            "brain", "brain", outcome, (monotonic() - started) * 1000,
            host=_brain_host(path, method), error=error, path=path,
            status=upstream.status_code, streaming=True,
        )
        await upstream.aclose()


class _BodyTooLarge(Exception):
    pass


async def _read_capped_body(request: Request, max_bytes: int) -> bytes:
    """Buffer the body for Brain, refusing as soon as it passes ``max_bytes``."""
    too_large = _BodyTooLarge(f"請求內容超過上限（{max_bytes // (1024 * 1024)} MB）")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise too_large
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise too_large
        chunks.append(chunk)
    return b"".join(chunks)


async def proxy_to_brain(
    request: Request,
    path: str,
    *,
    current: CurrentAccount | None,
    project_id: str | None = None,
) -> Response:
    """Forward a request with identity supplied only by trusted Backend state."""
    vendor = current is not None and is_vendor_account(current.user)
    if vendor and not vendor_route_allowed(request.method, request.scope["path"]):
        return JSONResponse(status_code=403, content={"detail": "沒有權限使用這個功能。"})
    alias = KNOWLEDGE_DOCUMENT_ROUTES.get(f"/{path}")
    if alias:
        path = alias.removeprefix("/")
    normalized_path = path.strip("/")
    # HTTPX resolves dot segments before forwarding. Reject them before checking
    # route ownership and project access so both layers see the same target.
    if any(segment in {".", ".."} for segment in normalized_path.split("/")):
        return JSONResponse(status_code=404, content={"detail": "Resource not found"})
    if any(
        normalized_path == prefix or normalized_path.startswith(f"{prefix}/")
        for prefix in _BACKEND_OWNED_PREFIXES
    ):
        return JSONResponse(status_code=404, content={"detail": "Resource not found"})
    # 先讀 body（受大小上限保護）：授權要看 body 裡的 project_id，不能為了授權
    # 先把整個 body 不設上限地讀進記憶體。
    try:
        body = await _read_capped_body(request, get_tts_config().brain_proxy_max_body_bytes)
    except _BodyTooLarge as exc:
        return JSONResponse(status_code=413, content={"detail": str(exc)})
    if vendor and alias:
        if request.method in {"GET", "DELETE"}:
            fields = [request.query_params.get("path")]
        else:
            payload = brain_project_access.proxy_json_object(body) or {}
            keys = ("source_path", "target_path") if path == "knowledge/move" else ("path",)
            fields = [payload.get(key) for key in keys]
        if not all(is_vendor_knowledge_path(field) for field in fields):
            return JSONResponse(status_code=403, content={"detail": "沒有權限使用這個功能。"})
    try:
        project_id = await brain_project_access.authorize_project_context(
            request,
            path,
            current,
            project_id,
            body,
        )
    except ResourceNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"detail": "Resource not found"},
        )
    except brain_project_access.InvalidProjectId as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except HTTPException as exc:
        if vendor and exc.status_code == 403:
            return JSONResponse(status_code=403, content={"detail": "沒有權限使用這個功能。"})
        raise
    headers = _trusted_upstream_headers(
        request,
        current=current,
        project_id=project_id,
    )
    if vendor:
        headers[VENDOR_HEADER] = "1"
    if project_writes := getattr(request.state, "project_writes", None):
        headers[_PROJECT_WRITES_HEADER] = project_writes
    try:
        body = guard_ai_cleanup(normalized_path, request.method, body, current)
    except AiCleanupRefused as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    # 範圍可能只寫在 body，要讀完 body 才判斷得了。
    refusal = skill_request_refusal(
        request, normalized_path, body, current, project_id,
    )
    if refusal is not None:
        return refusal
    query = brain_project_access.raw_query(request)
    if current is not None and project_id and brain_project_access.requires_project_context(path):
        query, body = brain_project_access.bind_project(request, body, project_id)
    client = _http.get()
    started = monotonic()

    def _attempt(outcome: str, error: str = "", status: int | None = None) -> None:
        emit_attempt(
            "brain", "brain", outcome, (monotonic() - started) * 1000,
            host=_brain_host(path, request.method), error=error, path=path, status=status,
        )

    try:
        upstream = await _unless_client_gone(
            request,
            client.send(
                client.build_request(
                    method=request.method,
                    url=_target_url(path, query, request.method),
                    headers=headers,
                    content=body,
                ),
                stream=True,
            ),
        )
        content_type = upstream.headers.get("content-type", "")
        resp_headers = _filter_headers(upstream.headers)

        if vendor and upstream.is_error:
            await upstream.aclose()
            detail = {
                403: "沒有權限使用這個功能。",
                404: "找不到指定的資料。",
                409: "資料已變更，請重新載入再試。",
            }.get(upstream.status_code, "操作失敗，請確認輸入後再試。")
            return JSONResponse(status_code=upstream.status_code, content={"detail": detail})

        # SSE / streaming responses — forward chunks via StreamingResponse.
        if "text/event-stream" in content_type:
            body_stream = _stream_upstream_bytes(
                upstream, path=path, started=started, sse=True,
                method=request.method,
            )
            if normalized_path in TTS_TEXT_STREAM_PATHS and upstream.status_code == 200:
                body_stream = annotate_sse(body_stream)
            return StreamingResponse(
                body_stream,
                status_code=upstream.status_code,
                media_type="text/event-stream",
                headers=resp_headers,
            )

        # Non-streaming: read full body, close stream, return plain Response.
        try:
            content = await _unless_client_gone(request, upstream.aread())
        finally:
            await upstream.aclose()

        _attempt(OK, status=upstream.status_code)
        if (
            normalized_path in TTS_TEXT_PATHS
            and upstream.status_code == 200
            and "json" in content_type
        ):
            content = annotate_json_body(content)
            # 長度變了；讓 Response 自己重算。
            resp_headers.pop("content-length", None)

        return Response(
            content=content,
            status_code=upstream.status_code,
            media_type=content_type or "application/json",
            headers=resp_headers,
        )
    except _ClientDisconnected:
        _attempt(ERROR, "client disconnected")
        logger.info(
            "client disconnected; closed brain request method=%s path=%s",
            log_safe(request.method), log_safe(path),
        )
        return Response(status_code=CLIENT_CLOSED_REQUEST)
    except httpx.TimeoutException as exc:
        outcome, error = classify_outcome(exc)
        _attempt(outcome, error)
        logger.warning(
            "brain request timeout path=%s outcome=%s error=%s",
            log_safe(path), log_safe(outcome), log_safe(error),
        )
        return JSONResponse(
            content={"error": "brain request timeout"},
            status_code=504,
        )
    except httpx.ConnectError as exc:
        _attempt(*classify_outcome(exc))
        logger.warning(
            "brain unreachable at %s: %s",
            _brain_host(path, request.method), describe_error(exc),
        )
        return JSONResponse(
            content={"error": "brain service unavailable"},
            status_code=502,
        )
    except httpx.RemoteProtocolError as exc:
        _attempt(*classify_outcome(exc))
        logger.warning(
            "brain upstream disconnected path=%s error=%s",
            log_safe(path), log_safe(describe_error(exc)),
        )
        return JSONResponse(
            content={"error": "brain upstream disconnected"},
            status_code=502,
        )
    except httpx.ReadError as exc:
        _attempt(*classify_outcome(exc))
        logger.warning(
            "brain upstream read error path=%s error=%s",
            log_safe(path), log_safe(describe_error(exc)),
        )
        return JSONResponse(
            content={"error": "brain upstream read error"},
            status_code=502,
        )
    except httpx.RequestError as exc:
        _attempt(*classify_outcome(exc))
        logger.warning(
            "brain request error path=%s error=%s",
            log_safe(path), log_safe(describe_error(exc)),
        )
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
    # 用 ASGI 的 path 而非 request.url.path：後者由字串重組再切開，解碼出的 ? 會
    # 把路徑截斷，授權與轉送看到的就不是同一條路徑。
    return request.scope["path"].removeprefix(f"{_PUBLIC_API_PREFIX}/").lstrip("/")


def _catchall_current_account(request: Request) -> CurrentAccount | None:
    # 跟 FailClosedAuthMiddleware 一樣看 ASGI 的 path：request.url.path 由字串重組
    # 再切開，路徑裡解碼出的 ? 會把它截成看起來像公開路徑的樣子。
    if (
        request.scope["path"] in _PUBLIC_BRAIN_PATHS
        # 公開的只有讀取；POST 之類若也免登入，會帶著內部 token 打到 Brain。
        and request.method.upper() in brain_project_access.SAFE_METHODS
    ):
        return None
    existing = getattr(request.state, "current_account", None)
    if isinstance(existing, CurrentAccount):
        return existing
    return authenticate_request(request, get_auth_runtime())


async def documented_brain_proxy(request: Request) -> Response:
    return await _proxy_to_brain(request, _request_brain_path(request))


def _documented_responses(route_def: dict[str, Any]) -> dict[int | str, dict[str, Any]]:
    responses: dict[int | str, dict[str, Any]] = {}
    if route_def.get("response_class") == "event_stream":
        responses.update(_EVENT_STREAM_RESPONSES)
    if route_def["path"] in _CHAT_PATHS:
        responses.update(_CHAT_RESPONSES)
    brain_path = route_def["path"].removeprefix(f"{_PUBLIC_API_PREFIX}/")
    if route_def["path"] not in _PUBLIC_BRAIN_PATHS and brain_project_access.requires_project_context(
        brain_path
    ):
        responses.update(_PROJECT_CONTEXT_RESPONSES)
    method = route_def["methods"][0]
    if brain_path == brain_project_access.PROJECT_FEATURES_PATH:
        responses[403] = {"description": "需要該專案的「改其他設定」權限"}
    if is_skill_write(brain_path.strip("/"), method):
        # 沒寫 scope=project 的請求一律視為共用技能。
        responses[403] = {
            "description": (
                "共用技能只有 ROOT 能啟用或停用"
                if is_skill_toggle(brain_path.strip("/"), method)
                else "共用技能在後台唯讀，改檔案、刪除、建立一律拒絕"
            ),
        }
    return responses


for route_def in _BRAIN_ROUTE_DEFS:
    router.add_api_route(
        route_def["path"],
        documented_brain_proxy,
        methods=route_def["methods"],
        tags=route_def["tags"],
        summary=route_def["summary"],
        responses=_documented_responses(route_def),
        response_class=(
            _EventStreamResponse
            if route_def.get("response_class") == "event_stream"
            else JSONResponse
        ),
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
    if path.strip("/").partition("/")[0] == "projects":
        return JSONResponse(status_code=404, content={"detail": "Resource not found"})
    return await _proxy_to_brain(request, path)

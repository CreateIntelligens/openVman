"""Project authorization and request binding for the Backend Brain proxy."""

from __future__ import annotations

import json
from posixpath import normpath
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode

from fastapi import HTTPException, Request, status

from app.auth.dependencies import CurrentAccount
from app.auth.embed import enforce_project_binding
from app.auth.models import ResourceType
from app.auth.resources import (
    ResourceAccess,
    ResourceNotFoundError,
    resolve_resource,
)
from app.auth.runtime import get_auth_runtime
from app.project_ids import canonical_project_id

PROJECT_FEATURES_PATH = "knowledge/features"
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
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def invalid_project_id_detail(code: str) -> str:
    """Map an InvalidProjectId reason code to a fixed client-facing message."""
    if code == "repeated":
        return "project_id must appear only once"
    if code == "empty":
        return "project_id must not be empty"
    if code == "non_empty_string":
        return "project_id must be a non-empty string"
    if code == "mismatch":
        return "project_id in query and body must match"
    if code == "required":
        return "project_id is required"
    return "Invalid project_id"


class InvalidProjectId(Exception):
    """The request did not name exactly one project."""

    def __init__(self, message: str, *, code: str = "") -> None:
        self.code = code
        super().__init__(message)


def raw_query(request: Request) -> str:
    """The query string exactly as authorization parsed it (``request.query_params``).

    ``request.url.query`` is re-split from a rebuilt URL, so a decoded ``?`` or ``#``
    in the path would make it differ from what was authorized.
    """
    return request.scope.get("query_string", b"").decode("latin-1")


def _reject_repeated_project_id(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # json.loads 遇到重複的鍵只留最後一個；專案 ID 寫兩次就是請求本身有歧義，不替呼叫端挑。
    if sum(1 for key, _ in pairs if key == "project_id") > 1:
        raise InvalidProjectId("project_id must appear only once", code="repeated")
    return dict(pairs)


def proxy_json_object(body: bytes) -> dict[str, Any] | None:
    """The body as Brain's FastAPI would see it: JSON whatever the Content-Type says."""
    if not body.strip():
        return None
    try:
        payload = json.loads(body, object_pairs_hook=_reject_repeated_project_id)
    except (UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _project_id_holders(payload: dict[str, Any]) -> list[dict[str, Any]]:
    # Brain 讀 body 最上層的 project_id；對話信封另外會讀 message.project_id。
    holders = [payload]
    message = payload.get("message")
    if isinstance(message, dict):
        holders.append(message)
    return holders


def _request_project_id(request: Request, body: bytes) -> str | None:
    """The single project the request names, from the query and the JSON body.

    Brain 讀 query 時取最後一個值、空字串會落到預設專案；body 沒有 Content-Type
    也照 JSON 解析。這裡任何一個來源跟其他來源不同、或 query 給了空值，都當成
    請求格式錯誤，不猜呼叫端要哪一個。
    """
    candidates: list[str] = []
    query_values = request.query_params.getlist("project_id")
    if len(query_values) > 1:
        raise InvalidProjectId("project_id must appear only once", code="repeated")
    for value in query_values:
        query_project_id = canonical_project_id(value)
        if not query_project_id:
            raise InvalidProjectId("project_id must not be empty", code="empty")
        candidates.append(query_project_id)

    payload = proxy_json_object(body)
    for holder in _project_id_holders(payload) if payload is not None else []:
        body_project_id = holder.get("project_id")
        if body_project_id is None or body_project_id == "":
            # 空值在轉送時會被換成授權的專案，不必擋。
            continue
        if not isinstance(body_project_id, str) or not canonical_project_id(body_project_id):
            raise InvalidProjectId("project_id must be a non-empty string", code="non_empty_string")
        candidates.append(canonical_project_id(body_project_id))

    if not candidates:
        return None
    if len(set(candidates)) != 1:
        raise InvalidProjectId("project_id in query and body must match", code="mismatch")
    return candidates[0]


def bind_project(request: Request, body: bytes, project_id: str) -> tuple[str, bytes]:
    """Rewrite the forwarded query and JSON body to name only the authorized project.

    授權用的是 ``project_id``；Brain 各路由從 query、body 或對話信封自己讀專案，
    沒寫時退回預設專案。轉送前把每個位置都寫成同一個值，Brain 就不會用到
    沒授權的專案。
    """
    pairs = [
        (key, value)
        for key, value in parse_qsl(raw_query(request), keep_blank_values=True)
        if key != "project_id"
    ]
    pairs.append(("project_id", project_id))
    query = urlencode(pairs, quote_via=quote)

    payload = proxy_json_object(body)
    if payload is None:
        return query, body
    for holder in _project_id_holders(payload):
        if holder is payload or "project_id" in holder:
            holder["project_id"] = project_id
    # 用 \\u 跳脫輸出：使用者內容可能含沒配對的 UTF-16 代理字元，直接編成 UTF-8 會丟例外變成 500。
    return query, json.dumps(payload).encode("utf-8")


def requires_project_context(path: str) -> bool:
    normalized = path.strip("/")
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in _PROJECT_SCOPED_PREFIXES
    )


def _project_access(path: str, method: str) -> ResourceAccess:
    normalized = path.strip("/")
    if method.upper() in SAFE_METHODS:
        return ResourceAccess.READ
    if normalized == PROJECT_FEATURES_PATH:
        return ResourceAccess.EDIT_SETTINGS
    project_area = normalized.partition("/")[0]
    if project_area in {"knowledge", "personas"}:
        return ResourceAccess.EDIT_KNOWLEDGE
    if project_area in {"dreaming", "memories", "sessions", "skills", "tools"}:
        return ResourceAccess.EDIT_SETTINGS
    return ResourceAccess.READ


_WORKSPACE_WRITES = frozenset({
    "knowledge/document", "knowledge/document/meta", "knowledge/directory", "knowledge/move",
    "knowledge/renormalize", "knowledge/renormalize/preview", "knowledge/renormalize/apply",
})
_PERSONA_DOCUMENTS = frozenset({"SOUL.md", "IDENTITY.md", "AGENTS.md", "TOOLS.md"})
_PROJECT_WRITES = (ResourceAccess.EDIT_KNOWLEDGE, ResourceAccess.EDIT_SETTINGS)


def _workspace_access(path: str) -> ResourceAccess:
    # Brain 再依實際解析到的檔案比對可信的寫入權限，避免符號連結跨越權限。
    parts = normpath(path.strip()).split("/")
    if (
        parts[0] in {"knowledge", "raw"}
        or (len(parts) == 1 and parts[0] in _PERSONA_DOCUMENTS)
        or (
            parts[0] == "personas"
            and (len(parts) <= 2 or (len(parts) == 3 and parts[-1] in _PERSONA_DOCUMENTS))
        )
    ):
        return ResourceAccess.EDIT_KNOWLEDGE
    return ResourceAccess.EDIT_SETTINGS


def _workspace_project_writes(
    request: Request, path: str, body: bytes,
) -> tuple[ResourceAccess, ...]:
    if request.method == "DELETE":
        fields = [request.query_params.get("path")]
    else:
        payload = proxy_json_object(body) or {}
        fields = (
            [payload.get("source_path"), payload.get("target_path")]
            if path == "knowledge/move"
            else [payload.get("path")]
        )
    required = {_workspace_access(field) for field in fields if isinstance(field, str)}
    return tuple(access for access in _PROJECT_WRITES if access in required) or (
        ResourceAccess.EDIT_KNOWLEDGE,
    )


async def authorize_project_context(
    request: Request,
    path: str,
    current: CurrentAccount | None,
    explicit_project_id: str | None,
    body: bytes = b"",
) -> str | None:
    if current is None or not requires_project_context(path):
        return explicit_project_id

    if current.embed_key is not None:
        # Embed key 沒有資源授權，專案由金鑰本身綁定；client 自帶不同的
        # project_id 一律 403，不能靜默改用金鑰的專案。
        enforce_project_binding(
            current.embed_key,
            _request_project_id(request, body) or "",
        )
        # 金鑰可能在 default 拔掉前就綁了 "default"，一樣換成預設專案的正式 ID。
        embed_project_id = canonical_project_id(current.embed_key.project_id)
        request.state.resolved_project_id = embed_project_id
        return embed_project_id

    supplied_project_id = _request_project_id(request, body)
    if explicit_project_id is not None:
        explicit_project_id = canonical_project_id(explicit_project_id) or None
    resolved_project_id = explicit_project_id or supplied_project_id
    if (
        explicit_project_id is not None
        and supplied_project_id is not None
        and supplied_project_id != explicit_project_id
    ):
        raise InvalidProjectId("project_id in query and body must match", code="mismatch")
    if resolved_project_id is None:
        # 缺欄位是請求格式問題，回 422 才不會讓串接方以為專案不存在；
        # 專案看不到仍是 404，不洩漏存在與否。
        raise InvalidProjectId("project_id is required", code="required")

    runtime = get_auth_runtime()
    access = _project_access(path, request.method)
    normalized_path = path.strip("/")
    workspace_write = access is ResourceAccess.EDIT_KNOWLEDGE and normalized_path in _WORKSPACE_WRITES
    required = (
        _workspace_project_writes(request, normalized_path, body)
        if workspace_write else (access,)
    )

    def resolve(permission: ResourceAccess) -> None:
        resolve_resource(
            runtime.resources, current.user, ResourceType.PROJECT,
            resolved_project_id, access=permission,
        )

    try:
        for permission in required:
            resolve(permission)
    except ResourceNotFoundError:
        # 看得到專案、只是不能改（例如一般帳號刪對話、改知識庫）就明說 403；
        # 回 404 會讓串接方以為專案或對話不存在。看不到的專案照舊 404，不洩漏存在與否。
        if access is ResourceAccess.READ:
            raise
        resolve(ResourceAccess.READ)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account cannot modify this project",
        ) from None
    if workspace_write:
        allowed = list(required)
        for permission in _PROJECT_WRITES:
            if permission in required:
                continue
            try:
                resolve(permission)
            except ResourceNotFoundError:
                continue
            allowed.append(permission)
        request.state.project_writes = ",".join(permission.value for permission in allowed)
    elif normalized_path == PROJECT_FEATURES_PATH and access is ResourceAccess.EDIT_SETTINGS:
        request.state.project_writes = access.value
    request.state.resolved_project_id = resolved_project_id
    return resolved_project_id

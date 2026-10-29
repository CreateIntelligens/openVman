from __future__ import annotations

import logging
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app import voice_policy
from app.auth.dependencies import (
    CurrentAccount,
    get_current_account,
    require_admin,
    require_root,
)
from app.auth.models import (
    AccountRole,
    AccountType,
    ResourceType,
    is_at_least_admin,
)
from app.auth.resources import resolve_admin_scope
from app.auth.runtime import AuthRuntime, get_auth_runtime
from app.auth.voice_access import embed_tts_providers, scoped_tts_providers
from app.config import get_tts_config
from app.gateway.redis_pool import redis_available
from app.gateway.temp_storage import get_temp_storage
from app.health_payloads import build_backend_health_payload
from app.http_client import SharedAsyncClient
from app.observability import build_prometheus_response, get_metrics_snapshot
from app.project_ids import canonical_project_id
from app.providers.voice_catalog import build_tts_provider_catalog, fetch_voxcpm_models

logger = logging.getLogger("backend")
router = APIRouter()
_health_http = SharedAsyncClient()
_INTERNAL_TOKEN_HEADER = "X-Internal-Token"
_USAGE_TIMEOUT_SECONDS = 5


async def close_http() -> None:
    await _health_http.close()


@router.get("/healthz", tags=["System"], summary="服務健康檢查")
async def healthz() -> dict:
    storage = get_temp_storage()
    quota = storage.check_quota()
    payload = await build_backend_health_payload(
        service="tts-router",
        redis_available=await redis_available(),
        quota=quota,
        client=_health_http.get(),
    )
    dependencies = cast(dict[str, Any], payload["dependencies"])
    try:
        unreadable = get_auth_runtime().model_providers.unreadable_credentials()
    except Exception as exc:  # noqa: BLE001 - 健康檢查本身不能因為這項掛掉
        logger.warning("model provider key check failed: %s", exc)
        dependencies["model_provider_keys"] = {"status": "unknown"}
        return payload
    # 加密 secret 換掉時這些 key 解不開、暫用 .env；標 degraded 讓監控看得到。
    dependencies["model_provider_keys"] = {
        "status": "error" if unreadable else "ok",
        "unreadable": unreadable,
    }
    if unreadable:
        payload["status"] = "degraded"
    return payload


UsageEndpoint = Literal["summary", "timeseries", "events"]
_USAGE_QUERY_KEYS: dict[UsageEndpoint, frozenset[str]] = {
    "timeseries": frozenset({
        "report_timezone",
        "bucket",
        "group_by",
        "limit",
        "user_id",
        "principal_type",
        "principal_id",
        "project_id",
        "session_id",
        "kind",
        "since",
        "until",
    }),
    "summary": frozenset({
        "group_by",
        "user_id",
        "principal_type",
        "principal_id",
        "project_id",
        "session_id",
        "kind",
        "since",
        "until",
    }),
    "events": frozenset({
        "limit",
        "user_id",
        "principal_type",
        "principal_id",
        "project_id",
        "session_id",
        "trace_id",
        "kind",
        "since",
        "until",
    }),
}


async def _forward_usage_query(
    request: Request,
    current: CurrentAccount,
    endpoint: UsageEndpoint,
) -> JSONResponse:
    """Proxy a usage query to Brain, scoping non-admin accounts to themselves.

    Brain 的 ledger 沒有帳號概念，只認 header 帶進去的 user_id，所以權限
    收在這裡：管理員可帶任意 filter，其餘帳號的 user_id 一律覆寫成自己。
    受限管理員只看得到範圍內的專案：指定範圍外的專案回 404，沒指定就只查
    範圍內的專案。
    """
    params: dict[str, str | list[str]] = {
        key: value
        for key, value in request.query_params.items()
        if key in _USAGE_QUERY_KEYS[endpoint] and value
    }
    is_admin = (
        current.user.account_type is AccountType.FORMAL
        and is_at_least_admin(current.user.role)
    )
    if not is_admin:
        params["user_id"] = current.user.id
    else:
        scope = resolve_admin_scope(current.user, get_auth_runtime().admin_scopes)
        if scope.scoped:
            allowed = scope.resource_ids(ResourceType.PROJECT)
            requested = canonical_project_id(cast(str, params.get("project_id", "")))
            if requested and requested not in allowed:
                # 範圍外的專案跟不存在一樣，不洩漏它有沒有用量。
                return JSONResponse(status_code=404, content={"detail": "Resource not found"})
            if requested:
                params["project_id"] = requested
            else:
                # 空清單也要帶：Brain 收到空的 project_ids 一筆都不回，不會變成不篩選。
                params["project_ids"] = sorted(allowed) or [""]

    cfg = get_tts_config()
    url = f"{cfg.brain_url.rstrip('/')}/brain/usage/{endpoint}"
    try:
        response = await _health_http.get().get(
            url,
            params=params,
            headers={_INTERNAL_TOKEN_HEADER: cfg.gateway_internal_token},
            timeout=_USAGE_TIMEOUT_SECONDS,
        )
        content = response.json()
    except Exception as exc:
        logger.warning("usage query to brain failed: %s", exc)
        return JSONResponse(status_code=502, content={"error": "brain unavailable"})
    if response.status_code == 200 and isinstance(content, dict):
        _label_usage_accounts(content)
    return JSONResponse(status_code=response.status_code, content=content)


def _account_labels(user_ids: set[str]) -> dict[str, str]:
    """Map account ids to display names, falling back to the raw id."""
    runtime = get_auth_runtime()
    labels: dict[str, str] = {}
    for user_id in user_ids:
        if not user_id:
            continue
        try:
            user = runtime.users.get_by_id(user_id)
        except Exception:  # noqa: BLE001 - 標籤缺失不該讓整份報表失敗
            user = None
        labels[user_id] = user.username if user else user_id
    return labels


def _label_usage_accounts(content: dict[str, object]) -> None:
    """Annotate ledger rows keyed by ``user_id`` with a readable username.

    Brain 的 ledger 只存 user_id，帳號名在 Backend 這側，所以在回程補上；
    前端因此不必為了顯示一個名字再打一次帳號 API。
    """
    rows: list[dict[str, object]] = []
    for key in ("groups", "series", "events"):
        value = content.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    if not rows:
        return
    labels = _account_labels({
        str(row.get("user_id") or "")
        for row in rows
        if row.get("user_id")
    })
    for row in rows:
        user_id = str(row.get("user_id") or "")
        if user_id in labels:
            row["username"] = labels[user_id]


@router.get("/api/v1/usage/summary", tags=["Usage"], summary="Token 用量彙總")
async def get_usage_summary(
    request: Request,
    current: CurrentAccount = Depends(get_current_account),
) -> JSONResponse:
    return await _forward_usage_query(request, current, "summary")


@router.get(
    "/api/v1/usage/timeseries",
    tags=["Usage"],
    summary="Token 用量時間序列",
)
async def get_usage_timeseries(
    request: Request,
    current: CurrentAccount = Depends(get_current_account),
) -> JSONResponse:
    return await _forward_usage_query(request, current, "timeseries")


@router.get("/api/v1/usage/events", tags=["Usage"], summary="Token 用量事件明細")
async def get_usage_events(
    request: Request,
    current: CurrentAccount = Depends(get_current_account),
) -> JSONResponse:
    return await _forward_usage_query(request, current, "events")


# 備份會讀遍所有專案的對話，大專案可能要十幾秒。
_BACKUP_TIMEOUT_SECONDS = 120.0


async def _forward_backup(method: str, body: dict | None = None) -> JSONResponse:
    cfg = get_tts_config()
    url = f"{cfg.brain_url.rstrip('/')}/brain/backups/sessions"
    try:
        response = await _health_http.get().request(
            method,
            url,
            json=body,
            headers={_INTERNAL_TOKEN_HEADER: cfg.gateway_internal_token},
            timeout=_BACKUP_TIMEOUT_SECONDS,
        )
        content = response.json()
    except Exception as exc:
        logger.warning("session backup call to brain failed: %s", exc)
        return JSONResponse(status_code=502, content={"error": "brain unavailable"})
    return JSONResponse(status_code=response.status_code, content=content)


@router.get("/api/v1/backups/sessions", tags=["Backups"], summary="列出對話備份（ROOT）")
async def get_session_backups(
    _root: CurrentAccount = Depends(require_root),
) -> JSONResponse:
    return await _forward_backup("GET")


@router.post("/api/v1/backups/sessions", tags=["Backups"], summary="立即備份對話（ROOT）")
async def post_session_backup(
    request: Request,
    _root: CurrentAccount = Depends(require_root),
) -> JSONResponse:
    """全部專案的對話依語言匯出；帶 ``{"dry_run": true}`` 只回數量不寫檔。

    限 ROOT：備份涵蓋每個專案的對話內容，跨專案權限只有 ROOT 有。
    """
    try:
        body = await request.json()
    except ValueError:
        body = {}
    dry_run = bool(body.get("dry_run")) if isinstance(body, dict) else False
    return await _forward_backup("POST", {"dry_run": dry_run})


@router.get("/metrics", tags=["System"], summary="服務監控指標")
async def metrics() -> dict:
    return get_metrics_snapshot()


@router.get("/metrics/prometheus", tags=["System"], summary="Prometheus 格式指標")
async def metrics_prometheus():
    return build_prometheus_response()


@router.get("/api/v1/tts/providers", tags=["TTS"], summary="取得 TTS Provider 清單")
async def get_tts_providers(
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
    project_id: str = "",
) -> JSONResponse:
    """帶 project_id 時只列這個專案允許的聲音（Embed key 一律用金鑰綁定的專案）。"""
    _project, policy = voice_policy.request_policy(runtime, current, project_id)
    if current.embed_key is not None:
        return JSONResponse(content=embed_tts_providers(current, runtime, policy))
    has_project_override = False
    if _project:
        if (
            runtime.project_resource_assignments.list_for_project(
                _project, resource_type=ResourceType.CUSTOM_VOICE
            )
            or runtime.resources.list_by_owner_project(
                _project, resource_type=ResourceType.CUSTOM_VOICE
            )
        ):
            has_project_override = True

    # ROOT 帶專案時要拿到已註冊的聲音與 in_project_scope 標記，完整型錄沒有這個欄位。
    if (bool(_project) and current.user.role is AccountRole.ROOT) or not (
        current.user.account_type is AccountType.FORMAL
        and is_at_least_admin(current.user.role)
    ) or resolve_admin_scope(current.user, runtime.admin_scopes).scoped or (
        # 完整型錄列的是上游的所有聲音，不是已註冊的資源，沒辦法套專案清單；
        # 專案有限制或有專案/指派聲音時改列已註冊且允許的聲音。
        (policy is not None and policy.restricts_tts) or has_project_override
    ):
        return JSONResponse(
            content=scoped_tts_providers(
                current, runtime, policy, project_id=_project
            )
        )

    providers = await build_tts_provider_catalog(get_tts_config())
    return JSONResponse(content=providers)


@router.get(
    "/api/v1/tts/voxcpm/models",
    tags=["TTS"],
    summary="VoxCPM 可選的模型（後台試聽用）",
)
async def get_voxcpm_models(
    current: CurrentAccount = Depends(require_admin),
) -> JSONResponse:
    """列出 VoxCPM catalog 裡的完整 checkpoint 與 LoRA；正式對話不指定模型。"""
    if current.embed_key is not None:
        return JSONResponse(status_code=403, content={"error": "Administrator access required"})
    cfg = get_tts_config()
    if not cfg.tts_voxcpm_url:
        return JSONResponse(content={"models": []})
    models = await fetch_voxcpm_models(cfg.tts_voxcpm_url, cfg.tts_voxcpm_api_key)
    return JSONResponse(content={"models": models})



@router.get(
    "/api/v1/admin/request-origins",
    tags=["System"],
    summary="外部網站呼叫紀錄（依來源網域與金鑰彙總）",
)
def list_request_origins(
    limit: int = 200,
    _root: CurrentAccount = Depends(require_root),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, Any]:
    records = runtime.request_origins.list_recent(limit)
    return {
        "origins": [
            {
                "origin": r.origin,
                "principal_type": r.principal_type,
                "principal_id": r.principal_id,
                "user_id": r.user_id,
                "first_seen_at": r.first_seen_at,
                "last_seen_at": r.last_seen_at,
                "last_path": r.last_path,
                "request_count": r.request_count,
            }
            for r in records
        ],
    }

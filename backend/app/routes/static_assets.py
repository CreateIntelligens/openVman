"""Authorized static asset serving router for mascots, backgrounds, and avatars."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from app.auth.dependencies import (
    CurrentAccount,
    authenticate_request,
    get_current_account,
)
from app.auth.models import (
    AccountType,
    ResourceRecord,
    ResourceType,
    ResourceVisibility,
    is_at_least_admin,
)
from app.auth.resources import ResourceNotFoundError, resolve_resource
from app.auth.runtime import AuthRuntime, get_auth_runtime
from app.config import get_tts_config

logger = logging.getLogger("backend.static_assets")
router = APIRouter(tags=["Static Assets"])


def _check_resource_access(
    current: CurrentAccount | None,
    runtime: AuthRuntime,
    resource_type: ResourceType,
    resource_id: str,
) -> ResourceRecord | None:
    record = runtime.resources.get(resource_type, resource_id)
    if current is None:
        if (
            record is None
            or record.visibility is not ResourceVisibility.SYSTEM_PUBLIC
        ):
            raise HTTPException(status_code=404, detail="File not found")
        return record
    if (
        current.user.account_type is AccountType.FORMAL
        and is_at_least_admin(current.user.role)
    ):
        if record is None:
            raise HTTPException(status_code=404, detail="File not found")
        return record
    if current.embed_key is not None:
        # Embed 主體沒有資源授權；能不能讀這個角色已經由 middleware 依
        # 金鑰的預設／額外角色清單判定過，這裡只確認資源存在。
        if record is None:
            raise HTTPException(status_code=404, detail="File not found")
        return record
    try:
        return resolve_resource(
            runtime.resources,
            current.user,
            resource_type,
            resource_id,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied to {resource_type.value}/{resource_id}",
        ) from exc


def _get_optional_current_account(
    request: Request,
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> CurrentAccount | None:
    existing = getattr(request.state, "current_account", None)
    if isinstance(existing, CurrentAccount):
        return existing
    if (
        request.headers.get("authorization") is None
        and "openvman_session" not in request.cookies
    ):
        return None
    return authenticate_request(request, runtime)


def _resolve_asset_file(
    base_directory: str,
    resource_id: str,
    relative_path: str,
) -> Path:
    base_dir = Path(base_directory).resolve()
    target = (base_dir / resource_id / relative_path).resolve()
    if not target.is_relative_to(base_dir) or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return target


@router.get("/static/mascots/{mascot_id}/{file_path:path}", summary="讀取小助理檔案")
async def get_mascot_asset(
    mascot_id: str,
    file_path: str,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> FileResponse:
    _check_resource_access(current, runtime, ResourceType.AVATAR_MASCOT, mascot_id)
    cfg = get_tts_config()
    return FileResponse(_resolve_asset_file(cfg.avatar_mascots_dir, mascot_id, file_path))


@router.get("/static/backgrounds/{background_id}/{file_path:path}", summary="讀取背景檔案")
async def get_background_asset(
    background_id: str,
    file_path: str,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> FileResponse:
    _check_resource_access(current, runtime, ResourceType.AVATAR_BACKGROUND, background_id)
    cfg = get_tts_config()
    return FileResponse(_resolve_asset_file(cfg.avatar_backgrounds_dir, background_id, file_path))


@router.get("/static/characters/{char_id}/{file_path:path}", summary="讀取角色檔案")
async def get_character_asset(
    char_id: str,
    file_path: str,
    current: CurrentAccount | None = Depends(_get_optional_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> FileResponse:
    resource = _check_resource_access(
        current,
        runtime,
        ResourceType.AVATAR_CHARACTER,
        char_id,
    )
    cfg = get_tts_config()
    cache_control = (
        "public, max-age=3600"
        if resource is not None
        and resource.visibility is ResourceVisibility.SYSTEM_PUBLIC
        else "private, no-store"
    )
    return FileResponse(
        _resolve_asset_file(cfg.avatar_assets_dir, char_id, file_path),
        headers={"Cache-Control": cache_control},
    )

"""Authorized static asset serving router for mascots, backgrounds, and avatars."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.auth.dependencies import CurrentAccount, get_current_account
from app.auth.models import AccountRole, AccountType, ResourceType
from app.auth.resources import ResourceNotFoundError, resolve_resource
from app.auth.runtime import AuthRuntime, get_auth_runtime
from app.config import get_tts_config

logger = logging.getLogger("backend.static_assets")
router = APIRouter(tags=["Static Assets"])


def _check_resource_access(
    current: CurrentAccount,
    runtime: AuthRuntime,
    resource_type: ResourceType,
    resource_id: str,
) -> None:
    if (
        current.user.account_type is AccountType.FORMAL
        and current.user.role is AccountRole.ADMIN
    ):
        return
    try:
        resolve_resource(
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


@router.get("/mascots/{mascot_id}/{file_path:path}", summary="讀取小助理檔案")
async def get_mascot_asset(
    mascot_id: str,
    file_path: str,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> FileResponse:
    _check_resource_access(current, runtime, ResourceType.AVATAR_MASCOT, mascot_id)
    cfg = get_tts_config()
    return FileResponse(_resolve_asset_file(cfg.avatar_mascots_dir, mascot_id, file_path))


@router.get("/backgrounds/{background_id}/{file_path:path}", summary="讀取背景檔案")
async def get_background_asset(
    background_id: str,
    file_path: str,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> FileResponse:
    _check_resource_access(current, runtime, ResourceType.AVATAR_BACKGROUND, background_id)
    cfg = get_tts_config()
    return FileResponse(_resolve_asset_file(cfg.avatar_backgrounds_dir, background_id, file_path))


@router.get("/assets/{char_id}/{file_path:path}", summary="讀取角色檔案")
async def get_character_asset(
    char_id: str,
    file_path: str,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> FileResponse:
    _check_resource_access(current, runtime, ResourceType.AVATAR_CHARACTER, char_id)
    cfg = get_tts_config()
    return FileResponse(_resolve_asset_file(cfg.avatar_assets_dir, char_id, file_path))

"""Avatar stage background asset management API."""

from __future__ import annotations

import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel, Field

from app.auth.dependencies import (
    CurrentAccount,
    get_current_account,
    require_admin,
)
from app.auth.models import ResourceType
from app.auth.resources import list_accessible_resources
from app.auth.runtime import AuthRuntime, get_auth_runtime
from app.avatar.background_store import (
    AvatarBackgroundStore,
    BackgroundExists,
    BackgroundNotFound,
)
from app.avatar.background_validation import (
    InvalidBackgroundId,
    InvalidBackgroundUpload,
    normalize_background_id,
)
from app.config import get_tts_config

logger = logging.getLogger("backend.backgrounds")
router = APIRouter()

_store: AvatarBackgroundStore | None = None


def get_store() -> AvatarBackgroundStore:
    global _store
    if _store is None:
        cfg = get_tts_config()
        _store = AvatarBackgroundStore(base_dir=cfg.avatar_backgrounds_dir)
    return _store


def reset_store() -> None:
    global _store
    _store = None


class UpdateLabelRequest(BaseModel):
    label: str = Field(..., min_length=1)


def _normalize_background_id_or_400(background_id: str) -> str:
    try:
        return normalize_background_id(background_id)
    except InvalidBackgroundId as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/v1/backgrounds", summary="列出 Avatar 背景")
async def list_backgrounds(
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
):
    accessible_ids = {
        resource.resource_id
        for resource in list_accessible_resources(
            runtime.resources,
            current.user,
            ResourceType.AVATAR_BACKGROUND,
        )
    }
    return {
        "backgrounds": [
            bg
            for bg in get_store().list_backgrounds()
            if bg.get("background_id") in accessible_ids
        ]
    }


@router.post("/api/v1/backgrounds", summary="上傳 Avatar 背景")
async def create_background(
    background_id: str = Form(...),
    label: str = Form(""),
    image: UploadFile = File(...),
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
):
    cfg = get_tts_config()
    bid = _normalize_background_id_or_400(background_id)
    image_bytes = await image.read()

    if len(image_bytes) > cfg.avatar_background_max_upload_bytes:
        raise HTTPException(status_code=413, detail="上傳檔案過大")

    try:
        background = get_store().create_background(
            background_id=bid,
            label=label,
            image_bytes=image_bytes,
            filename=image.filename or "",
        )
        try:
            runtime.resources.upsert_system_resource(
                resource_type=ResourceType.AVATAR_BACKGROUND,
                resource_id=bid,
                metadata={"label": label or bid},
            )
        except Exception as exc:
            logger.warning("failed to upsert background resource %s: %s", bid, exc)
    except InvalidBackgroundUpload as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BackgroundExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok", "background": background}


@router.delete("/api/v1/backgrounds/{background_id}", summary="刪除 Avatar 背景")
async def delete_background(
    background_id: str,
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
):
    bid = _normalize_background_id_or_400(background_id)
    try:
        get_store().delete_background(bid)
        try:
            runtime.resources.unregister(ResourceType.AVATAR_BACKGROUND, bid)
        except Exception as exc:
            logger.warning("failed to unregister background resource %s: %s", bid, exc)
    except BackgroundNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "background_id": bid}


@router.patch("/api/v1/backgrounds/{background_id}", summary="更新 Avatar 背景顯示名稱")
async def update_background_label(
    background_id: str,
    payload: UpdateLabelRequest,
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
):
    bid = _normalize_background_id_or_400(background_id)
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="label 不可為空")
    try:
        background = get_store().update_label(bid, label)
        try:
            runtime.resources.upsert_system_resource(
                resource_type=ResourceType.AVATAR_BACKGROUND,
                resource_id=bid,
                metadata={"label": label},
            )
        except Exception as exc:
            logger.warning("failed to update background metadata %s: %s", bid, exc)
    except BackgroundNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "background": background}

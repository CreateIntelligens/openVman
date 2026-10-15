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
from app.auth.models import AccountRole, ResourceType, ResourceVisibility
from app.auth.project_resources import effective_project_resources
from app.auth.resources import (
    ResourceAccess,
    ResourceNotFoundError,
    list_accessible_resources,
    resolve_resource,
)
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
    project_id: str | None = None,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
):
    if project_id:
        try:
            resolve_resource(
                runtime.resources,
                current.user,
                ResourceType.PROJECT,
                project_id,
                access=ResourceAccess.READ,
            )
        except ResourceNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"專案不存在或無權限存取：{project_id}",
            )
        entries = effective_project_resources(
            runtime, current.user, project_id, ResourceType.AVATAR_BACKGROUND
        )
        source_by_id = {e.resource_id: e.source for e in entries}
        backgrounds = []
        for bg in get_store().list_backgrounds():
            bid = bg.get("background_id")
            if bid in source_by_id:
                backgrounds.append({**bg, "source": source_by_id[bid]})
        return {"backgrounds": backgrounds}

    is_root = current.user.role is AccountRole.ROOT
    accessible = list_accessible_resources(
        runtime.resources,
        current.user,
        ResourceType.AVATAR_BACKGROUND,
    )
    accessible_sources = {
        resource.resource_id: (
            "orphan"
            if is_root
            and resource.visibility is ResourceVisibility.PROJECT
            and resource.owner_project_id is None
            else "grant"
        )
        for resource in accessible
        if resource.visibility is not ResourceVisibility.PROJECT
        or (is_root and resource.owner_project_id is None)
    }
    return {
        "backgrounds": [
            {**bg, "source": accessible_sources[bg["background_id"]]}
            for bg in get_store().list_backgrounds()
            if bg.get("background_id") in accessible_sources
        ]
    }


@router.post("/api/v1/backgrounds", summary="上傳 Avatar 背景")
async def create_background(
    background_id: str = Form(...),
    label: str = Form(""),
    image: UploadFile = File(...),
    project_id: str | None = Form(default=None),
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
):
    cfg = get_tts_config()
    bid = _normalize_background_id_or_400(background_id)
    norm_project_id = project_id.strip() if project_id and project_id.strip() else None
    if norm_project_id:
        project = runtime.resources.get(ResourceType.PROJECT, norm_project_id)
        if project is None:
            raise HTTPException(
                status_code=404,
                detail=f"專案不存在：{norm_project_id}",
            )
        if _admin.user.role is not AccountRole.ROOT:
            try:
                resolve_resource(
                    runtime.resources,
                    _admin.user,
                    ResourceType.PROJECT,
                    norm_project_id,
                    access=ResourceAccess.MUTATE,
                )
            except ResourceNotFoundError:
                raise HTTPException(
                    status_code=403,
                    detail=f"您沒有專案 {norm_project_id} 的管理權限",
                )

    existing = runtime.resources.get(ResourceType.AVATAR_BACKGROUND, bid)
    if existing is not None:
        if existing.owner_project_id is None:
            raise HTTPException(
                status_code=409,
                detail=f"背景 {bid} 已存在且為全域資源",
            )
        if existing.owner_project_id != norm_project_id:
            raise HTTPException(
                status_code=409,
                detail=f"背景 {bid} 已存在於其他專案",
            )

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
        if existing is not None:
            runtime.resources.update_metadata(
                ResourceType.AVATAR_BACKGROUND,
                bid,
                {"label": label or bid},
            )
        else:
            visibility = (
                ResourceVisibility.PROJECT
                if norm_project_id
                else ResourceVisibility.SYSTEM_PUBLIC
            )
            runtime.resources.register(
                resource_type=ResourceType.AVATAR_BACKGROUND,
                resource_id=bid,
                owner_user_id=None,
                visibility=visibility,
                owner_project_id=norm_project_id,
                metadata={"label": label or bid},
            )
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

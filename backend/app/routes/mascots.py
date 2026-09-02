"""Right-corner mascot asset management API."""

from __future__ import annotations

import logging
from typing import Any

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
from app.avatar.mascot_store import (
    VIDEO_ENGINE,
    MascotExists,
    MascotNotFound,
    MascotStore,
)
from app.avatar.mascot_validation import (
    InvalidMascotId,
    InvalidMascotUpload,
    normalize_mascot_id,
    validate_vrm_bytes,
)
from app.avatar.validation import InvalidCharId, normalize_char_id
from app.config import get_tts_config
from app.routes.avatar import get_store as get_character_store

logger = logging.getLogger("backend.mascots")
router = APIRouter()

_store: MascotStore | None = None


def get_store() -> MascotStore:
    global _store
    if _store is None:
        cfg = get_tts_config()
        _store = MascotStore(base_dir=cfg.avatar_mascots_dir)
    return _store


def reset_store() -> None:
    global _store
    _store = None


class UpdateLabelRequest(BaseModel):
    label: str = Field(..., min_length=1)


class CreateVideoMascotRequest(BaseModel):
    mascot_id: str = Field(..., min_length=1)
    label: str = ""
    character_id: str = Field(..., min_length=1)


def _normalize_mascot_id_or_400(mascot_id: str) -> str:
    try:
        return normalize_mascot_id(mascot_id)
    except InvalidMascotId as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/avatar/mascots", summary="列出右下角小助理")
async def list_mascots(
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, list[dict[str, Any]]]:
    accessible_ids = {
        resource.resource_id
        for resource in list_accessible_resources(
            runtime.resources,
            current.user,
            ResourceType.AVATAR_MASCOT,
        )
    }
    # 影片型小助理的影片與嘴型資料由 /assets/{char_id} 依角色授權提供；
    # 看不到角色的帳號連小助理也不列出，避免選了卻載不出來。
    accessible_character_ids = {
        resource.resource_id
        for resource in list_accessible_resources(
            runtime.resources,
            current.user,
            ResourceType.AVATAR_CHARACTER,
        )
    }
    return {
        "mascots": [
            mascot
            for mascot in get_store().list_mascots()
            if mascot.get("mascot_id") in accessible_ids
            and (
                mascot.get("engine") != VIDEO_ENGINE
                or mascot.get("character_id") in accessible_character_ids
            )
        ]
    }


@router.post("/api/avatar/mascots", summary="上傳右下角小助理 VRM")
async def create_mascot(
    mascot_id: str = Form(...),
    label: str = Form(""),
    model: UploadFile = File(...),
    thumbnail: UploadFile | None = File(None),
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, Any]:
    cfg = get_tts_config()
    mid = _normalize_mascot_id_or_400(mascot_id)
    model_bytes = await model.read()
    thumbnail_bytes = await thumbnail.read() if thumbnail else None

    if len(model_bytes) > cfg.avatar_mascot_max_upload_bytes:
        raise HTTPException(status_code=413, detail="上傳檔案過大")

    try:
        validate_vrm_bytes(model_bytes, filename=model.filename or "")
        mascot = get_store().create_mascot(
            mascot_id=mid,
            label=label,
            vrm_bytes=model_bytes,
            thumbnail_bytes=thumbnail_bytes,
        )
        try:
            runtime.resources.upsert_system_resource(
                resource_type=ResourceType.AVATAR_MASCOT,
                resource_id=mid,
                metadata={"label": label or mid},
            )
        except Exception as exc:
            logger.warning("failed to upsert mascot resource %s: %s", mid, exc)
    except InvalidMascotUpload as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MascotExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok", "mascot": mascot}


@router.post("/api/avatar/mascots/from-character", summary="以影片型 Avatar 角色建立小助理")
async def create_video_mascot(
    payload: CreateVideoMascotRequest,
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, Any]:
    mid = _normalize_mascot_id_or_400(payload.mascot_id)
    try:
        cid = normalize_char_id(payload.character_id)
    except InvalidCharId as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    characters = {
        character["char_id"]: character
        for character in get_character_store().list_characters()
    }
    character = characters.get(cid)
    if character is None:
        raise HTTPException(status_code=404, detail=f"角色不存在：{cid}")
    if not (character.get("has_video") and character.get("has_data")):
        raise HTTPException(status_code=400, detail="角色缺少影片或嘴型資料，無法作為小助理")

    label = payload.label.strip() or str(character.get("label") or cid)
    try:
        mascot = get_store().create_video_mascot(
            mascot_id=mid,
            label=label,
            character_id=cid,
        )
    except MascotExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        runtime.resources.upsert_system_resource(
            resource_type=ResourceType.AVATAR_MASCOT,
            resource_id=mid,
            metadata={"label": label, "character_id": cid},
        )
    except Exception as exc:
        logger.warning("failed to upsert mascot resource %s: %s", mid, exc)
    return {"status": "ok", "mascot": mascot}


@router.delete("/api/avatar/mascots/{mascot_id}", summary="刪除上傳的小助理")
async def delete_mascot(
    mascot_id: str,
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, str]:
    mid = _normalize_mascot_id_or_400(mascot_id)
    try:
        get_store().delete_mascot(mid)
        try:
            runtime.resources.unregister(ResourceType.AVATAR_MASCOT, mid)
        except Exception as exc:
            logger.warning("failed to unregister mascot resource %s: %s", mid, exc)
    except MascotNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "mascot_id": mid}


@router.patch("/api/avatar/mascots/{mascot_id}", summary="更新小助理顯示名稱")
async def update_mascot_label(
    mascot_id: str,
    payload: UpdateLabelRequest,
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, Any]:
    mid = _normalize_mascot_id_or_400(mascot_id)
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="label 不可為空")
    try:
        mascot = get_store().update_label(mid, label)
        try:
            runtime.resources.upsert_system_resource(
                resource_type=ResourceType.AVATAR_MASCOT,
                resource_id=mid,
                metadata={"label": label},
            )
        except Exception as exc:
            logger.warning("failed to update mascot metadata %s: %s", mid, exc)
    except MascotNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "mascot": mascot}


@router.post("/api/avatar/mascots/{mascot_id}/thumbnail", summary="自動更新或上傳小助理縮圖")
async def update_mascot_thumbnail(
    mascot_id: str,
    thumbnail: UploadFile = File(...),
    _admin: CurrentAccount = Depends(require_admin),
) -> dict[str, Any]:
    mid = _normalize_mascot_id_or_400(mascot_id)
    thumbnail_bytes = await thumbnail.read()
    try:
        mascot = get_store().update_thumbnail(mid, thumbnail_bytes)
    except MascotNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "mascot": mascot}

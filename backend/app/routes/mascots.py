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
from app.auth.models import AccountRole, ResourceType, ResourceVisibility
from app.auth.project_resources import (
    effective_project_resources,
    unscoped_resource_sources,
)
from app.auth.resources import (
    ResourceAccess,
    ResourceNotFoundError,
    resolve_resource,
)
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
from app.utils.images import validate_image
from app.utils.upload import UploadLimitError, as_http_exception, read_upload_limited

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
    project_id: str | None = None


def _normalize_mascot_id_or_400(mascot_id: str) -> str:
    try:
        return normalize_mascot_id(mascot_id)
    except InvalidMascotId as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/v1/avatar/mascots", summary="列出右下角小助理")
async def list_mascots(
    project_id: str | None = None,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, list[dict[str, Any]]]:
    store = get_store()
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
        mascot_entries = effective_project_resources(
            runtime, current.user, project_id, ResourceType.AVATAR_MASCOT
        )
        char_entries = effective_project_resources(
            runtime, current.user, project_id, ResourceType.AVATAR_CHARACTER
        )
        mascot_entry_by_id = {e.resource_id: e for e in mascot_entries}
        char_entry_by_id = {e.resource_id: e for e in char_entries}
        mascots = []
        for mascot in store.list_mascots():
            mid = mascot.get("mascot_id")
            if mid in mascot_entry_by_id:
                m_entry = mascot_entry_by_id[mid]
                if (
                    mascot.get("engine") != VIDEO_ENGINE
                    or mascot.get("character_id") in char_entry_by_id
                ):
                    c_entry = char_entry_by_id.get(mascot.get("character_id"))
                    in_scope = m_entry.in_project_scope and (
                        c_entry.in_project_scope if c_entry else True
                    )
                    mascots.append({
                        **mascot,
                        "source": m_entry.source,
                        "in_project_scope": in_scope,
                    })
        covered = {
            m.get("character_id")
            for m in mascots
            if m.get("engine") == VIDEO_ENGINE
        }
        for character in get_character_store().list_characters():
            char_id = character.get("char_id")
            if (
                char_id in char_entry_by_id
                and char_id not in covered
                and character.get("has_video")
                and character.get("has_data")
            ):
                c_entry = char_entry_by_id[char_id]
                item = store.video_mascot_from_character(character)
                item["source"] = c_entry.source
                item["in_project_scope"] = c_entry.in_project_scope
                mascots.append(item)
        return {"mascots": mascots}

    accessible_mascot_sources = unscoped_resource_sources(
        runtime, current.user, ResourceType.AVATAR_MASCOT,
    )
    accessible_char_sources = unscoped_resource_sources(
        runtime, current.user, ResourceType.AVATAR_CHARACTER,
    )

    mascots = [
        {
            **mascot,
            "source": accessible_mascot_sources[mascot["mascot_id"]][0],
            "owner_project_id": accessible_mascot_sources[mascot["mascot_id"]][1],
        }
        for mascot in store.list_mascots()
        if mascot.get("mascot_id") in accessible_mascot_sources
        and (
            mascot.get("engine") != VIDEO_ENGINE
            or mascot.get("character_id") in accessible_char_sources
        )
    ]
    covered = {
        m.get("character_id")
        for m in mascots
        if m.get("engine") == VIDEO_ENGINE
    }
    for character in get_character_store().list_characters():
        char_id = character.get("char_id")
        if (
            char_id in accessible_char_sources
            and char_id not in covered
            and character.get("has_video")
            and character.get("has_data")
        ):
            item = store.video_mascot_from_character(character)
            item["source"] = accessible_char_sources[char_id]
            mascots.append(item)
    return {"mascots": mascots}


async def _read_thumbnail(thumbnail: UploadFile, cfg: Any) -> bytes:
    data = await read_upload_limited(
        thumbnail, max_bytes=cfg.avatar_mascot_thumbnail_max_upload_bytes, label="縮圖",
    )
    validate_image(data, max_side=cfg.upload_image_max_side_px)
    return data


@router.post("/api/v1/avatar/mascots", summary="上傳右下角小助理 VRM")
async def create_mascot(
    mascot_id: str = Form(...),
    label: str = Form(""),
    model: UploadFile = File(...),
    thumbnail: UploadFile | None = File(None),
    project_id: str | None = Form(default=None),
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, Any]:
    cfg = get_tts_config()
    mid = _normalize_mascot_id_or_400(mascot_id)
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

    existing = runtime.resources.get(ResourceType.AVATAR_MASCOT, mid)
    if existing is not None:
        if existing.owner_project_id is None:
            raise HTTPException(
                status_code=409,
                detail=f"小助理 {mid} 已存在且為全域資源",
            )
        if existing.owner_project_id != norm_project_id:
            raise HTTPException(
                status_code=409,
                detail=f"小助理 {mid} 已存在於其他專案",
            )

    try:
        model_bytes = await read_upload_limited(
            model, max_bytes=cfg.avatar_mascot_max_upload_bytes, label="模型",
        )
        thumbnail_bytes = await _read_thumbnail(thumbnail, cfg) if thumbnail else None
    except UploadLimitError as exc:
        raise as_http_exception(exc) from exc

    try:
        validate_vrm_bytes(model_bytes, filename=model.filename or "")
        mascot = get_store().create_mascot(
            mascot_id=mid,
            label=label,
            vrm_bytes=model_bytes,
            thumbnail_bytes=thumbnail_bytes,
        )
        if existing is not None:
            runtime.resources.update_metadata(
                ResourceType.AVATAR_MASCOT,
                mid,
                {"label": label or mid},
            )
        else:
            visibility = (
                ResourceVisibility.PROJECT
                if norm_project_id
                else ResourceVisibility.SYSTEM_PUBLIC
            )
            runtime.resources.register(
                resource_type=ResourceType.AVATAR_MASCOT,
                resource_id=mid,
                owner_user_id=None,
                visibility=visibility,
                owner_project_id=norm_project_id,
                metadata={"label": label or mid},
            )
    except InvalidMascotUpload as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except MascotExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok", "mascot": mascot}


@router.post("/api/v1/avatar/mascots/from-character", summary="以影片型 Avatar 角色建立小助理")
async def create_video_mascot(
    payload: CreateVideoMascotRequest,
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, Any]:
    mid = _normalize_mascot_id_or_400(payload.mascot_id)
    norm_project_id = payload.project_id.strip() if payload.project_id and payload.project_id.strip() else None
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

    existing = runtime.resources.get(ResourceType.AVATAR_MASCOT, mid)
    if existing is not None:
        if existing.owner_project_id is None:
            raise HTTPException(
                status_code=409,
                detail=f"小助理 {mid} 已存在且為全域資源",
            )
        if existing.owner_project_id != norm_project_id:
            raise HTTPException(
                status_code=409,
                detail=f"小助理 {mid} 已存在於其他專案",
            )

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

    if existing is not None:
        runtime.resources.update_metadata(
            ResourceType.AVATAR_MASCOT,
            mid,
            {"label": label or mid},
        )
    else:
        visibility = (
            ResourceVisibility.PROJECT
            if norm_project_id
            else ResourceVisibility.SYSTEM_PUBLIC
        )
        runtime.resources.register(
            resource_type=ResourceType.AVATAR_MASCOT,
            resource_id=mid,
            owner_user_id=None,
            visibility=visibility,
            owner_project_id=norm_project_id,
            metadata={"label": label, "character_id": cid},
        )
    return {"status": "ok", "mascot": mascot}



@router.delete("/api/v1/avatar/mascots/{mascot_id}", summary="刪除上傳的小助理")
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


@router.patch("/api/v1/avatar/mascots/{mascot_id}", summary="更新小助理顯示名稱")
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


@router.post("/api/v1/avatar/mascots/{mascot_id}/thumbnail", summary="自動更新或上傳小助理縮圖")
async def update_mascot_thumbnail(
    mascot_id: str,
    thumbnail: UploadFile = File(...),
    _admin: CurrentAccount = Depends(require_admin),
) -> dict[str, Any]:
    mid = _normalize_mascot_id_or_400(mascot_id)
    try:
        thumbnail_bytes = await _read_thumbnail(thumbnail, get_tts_config())
    except UploadLimitError as exc:
        raise as_http_exception(exc) from exc
    try:
        mascot = get_store().update_thumbnail(mid, thumbnail_bytes)
    except MascotNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "mascot": mascot}

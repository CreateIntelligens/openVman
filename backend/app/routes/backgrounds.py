"""Avatar stage background asset management API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

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


@router.get("/api/backgrounds", summary="列出 Avatar 背景")
async def list_backgrounds():
    return {"backgrounds": get_store().list_backgrounds()}


@router.post("/api/backgrounds", summary="上傳 Avatar 背景")
async def create_background(
    background_id: str = Form(...),
    label: str = Form(""),
    image: UploadFile = File(...),
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
    except InvalidBackgroundUpload as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BackgroundExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok", "background": background}


@router.delete("/api/backgrounds/{background_id}", summary="刪除 Avatar 背景")
async def delete_background(background_id: str):
    bid = _normalize_background_id_or_400(background_id)
    try:
        get_store().delete_background(bid)
    except BackgroundNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "background_id": bid}


@router.patch("/api/backgrounds/{background_id}", summary="更新 Avatar 背景顯示名稱")
async def update_background_label(background_id: str, payload: UpdateLabelRequest):
    bid = _normalize_background_id_or_400(background_id)
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="label 不可為空")
    try:
        background = get_store().update_label(bid, label)
    except BackgroundNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "background": background}

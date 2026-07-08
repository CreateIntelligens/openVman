"""Right-corner mascot asset management API."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.avatar.mascot_store import (
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
from app.config import get_tts_config

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


def _normalize_mascot_id_or_400(mascot_id: str) -> str:
    try:
        return normalize_mascot_id(mascot_id)
    except InvalidMascotId as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/avatar/mascots", summary="列出右下角小助理")
async def list_mascots() -> dict[str, list[dict[str, Any]]]:
    return {"mascots": get_store().list_mascots()}


@router.post("/api/avatar/mascots", summary="上傳右下角小助理 VRM")
async def create_mascot(
    mascot_id: str = Form(...),
    label: str = Form(""),
    model: UploadFile = File(...),
    thumbnail: UploadFile | None = File(None),
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
    except InvalidMascotUpload as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MascotExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok", "mascot": mascot}


@router.delete("/api/avatar/mascots/{mascot_id}", summary="刪除上傳的小助理")
async def delete_mascot(mascot_id: str) -> dict[str, str]:
    mid = _normalize_mascot_id_or_400(mascot_id)
    try:
        get_store().delete_mascot(mid)
    except MascotNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "mascot_id": mid}


@router.patch("/api/avatar/mascots/{mascot_id}", summary="更新小助理顯示名稱")
async def update_mascot_label(
    mascot_id: str,
    payload: UpdateLabelRequest,
) -> dict[str, Any]:
    mid = _normalize_mascot_id_or_400(mascot_id)
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="label 不可為空")
    try:
        mascot = get_store().update_label(mid, label)
    except MascotNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "mascot": mascot}


@router.post("/api/avatar/mascots/{mascot_id}/thumbnail", summary="自動更新或上傳小助理縮圖")
async def update_mascot_thumbnail(
    mascot_id: str,
    thumbnail: UploadFile = File(...),
) -> dict[str, Any]:
    mid = _normalize_mascot_id_or_400(mascot_id)
    thumbnail_bytes = await thumbnail.read()
    try:
        mascot = get_store().update_thumbnail(mid, thumbnail_bytes)
    except MascotNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "mascot": mascot}

"""Avatar character asset management API (prefix /api/avatar)."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.config import get_tts_config
from app.avatar.store import (
    AvatarStore,
    CharacterExists,
    CharacterNotFound,
)
from app.avatar.validation import (
    InvalidCharId,
    InvalidUpload,
    normalize_char_id,
    validate_data_bytes,
    validate_video_bytes,
)

logger = logging.getLogger("backend.avatar")
router = APIRouter()

_store: AvatarStore | None = None


def get_store() -> AvatarStore:
    global _store
    if _store is None:
        cfg = get_tts_config()
        _store = AvatarStore(base_dir=cfg.avatar_assets_dir)
    return _store


def reset_store() -> None:
    """Test hook — drop the cached store so a new base_dir takes effect."""
    global _store
    _store = None


class RenameRequest(BaseModel):
    new_char_id: str = Field(..., min_length=1)


def _normalize_char_id_or_400(char_id: str) -> str:
    try:
        return normalize_char_id(char_id)
    except InvalidCharId as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _read_upload_pair(video: UploadFile, data: UploadFile) -> tuple[bytes, bytes]:
    return await video.read(), await data.read()


def _personas_bound_to(char_id: str) -> list[str]:
    """Ask brain which personas are bound to this char_id.

    Fail safe: on brain error we raise (503) so we never delete a
    possibly-bound character silently.
    """
    cfg = get_tts_config()
    url = f"{cfg.brain_url}/brain/personas"
    try:
        resp = httpx.get(url, params={"project_id": "default"}, timeout=5.0)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"無法向 brain 確認 persona 綁定，操作中止：{exc}",
        ) from exc
    personas = resp.json().get("personas", [])
    return [p["persona_id"] for p in personas if p.get("avatar_char_id") == char_id]


def _guard_not_bound(char_id: str) -> None:
    bound = _personas_bound_to(char_id)
    if bound:
        raise HTTPException(
            status_code=409,
            detail=f"角色 {char_id} 仍被以下 persona 綁定，請先解除綁定：{', '.join(bound)}",
        )


@router.get("/api/avatar", summary="列出 Avatar 角色")
async def list_characters():
    return {"characters": get_store().list_characters()}


@router.post("/api/avatar", summary="上傳新 Avatar 角色")
async def create_character(
    char_id: str = Form(...),
    label: str = Form(""),
    video: UploadFile = File(...),
    data: UploadFile = File(...),
):
    cfg = get_tts_config()
    cid = _normalize_char_id_or_400(char_id)

    video_bytes, data_bytes = await _read_upload_pair(video, data)
    total = len(video_bytes) + len(data_bytes)
    if total > cfg.avatar_max_upload_bytes:
        raise HTTPException(status_code=413, detail="上傳檔案過大")

    try:
        validate_video_bytes(video_bytes, filename=video.filename or "")
        validate_data_bytes(data_bytes, filename=data.filename or "")
    except InvalidUpload as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        character = get_store().create_character(
            char_id=cid, label=label, video_bytes=video_bytes, data_bytes=data_bytes
        )
    except CharacterExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok", "character": character}


@router.delete("/api/avatar/{char_id}", summary="刪除 Avatar 角色")
async def delete_character(char_id: str):
    cid = _normalize_char_id_or_400(char_id)
    store = get_store()
    if not store.exists(cid):
        raise HTTPException(status_code=404, detail=f"角色不存在：{cid}")
    _guard_not_bound(cid)
    try:
        store.delete_character(cid)
    except CharacterNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "char_id": cid}


@router.post("/api/avatar/{char_id}/rename", summary="重命名 Avatar 角色")
async def rename_character(char_id: str, payload: RenameRequest):
    cid = _normalize_char_id_or_400(char_id)
    new_cid = _normalize_char_id_or_400(payload.new_char_id)
    store = get_store()
    if not store.exists(cid):
        raise HTTPException(status_code=404, detail=f"角色不存在：{cid}")
    _guard_not_bound(cid)
    try:
        character = store.rename_character(cid, new_cid)
    except CharacterExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CharacterNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "character": character}

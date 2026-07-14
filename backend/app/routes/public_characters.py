"""Public, unauthenticated character list for the Avatar embed SDK.

Read-only surface consumed by third-party sites via `GET /characters`.
Distinct from `app.routes.avatar`, which is the internal admin API for
uploading, renaming, and deleting characters — that API must stay behind
nginx and is not part of the SDK's public contract.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.avatar.store import AvatarStore
from app.config import get_tts_config

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


@router.get("/characters", summary="列出可供 Avatar SDK 使用的角色")
async def list_public_characters() -> dict:
    return {"characters": get_store().list_public_characters()}

"""Public, unauthenticated character list for the Avatar embed SDK.

Read-only surface consumed by third-party sites via `GET /api/v1/characters`.
Distinct from `app.routes.avatar`, which is the internal admin API for
uploading, renaming, and deleting characters — that API must stay behind
nginx and is not part of the SDK's public contract.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import CurrentAccount
from app.auth.models import EmbedKeyRecord, ResourceType, ResourceVisibility
from app.auth.runtime import AuthRuntime, get_auth_runtime
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


def _embed_project_character_ids(runtime: AuthRuntime, key: EmbedKeyRecord) -> set[str]:
    """Characters the key's project owns or was assigned, within the key's allowlist."""
    owned = {
        resource.resource_id
        for resource in runtime.resources.list_by_owner_project(key.project_id)
        if resource.resource_type is ResourceType.AVATAR_CHARACTER
    }
    assigned = {
        record.resource_id
        for record in runtime.project_resource_assignments.list_for_project(
            key.project_id, resource_type=ResourceType.AVATAR_CHARACTER,
        )
    }
    return {char_id for char_id in owned | assigned if key.allows_character(char_id)}


@router.get(
    "/api/v1/characters",
    summary="列出可供 Avatar SDK 使用的角色",
    description=(
        "不帶憑證時只列全域公開的人物。帶 `X-Embed-Key` 時另外列出金鑰綁定專案的專屬與"
        "ROOT 指派人物（限金鑰允許的人物）；這些人物的素材也要帶同一把金鑰才讀得到。"
    ),
)
async def list_public_characters(
    request: Request,
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict:
    visible_ids = {
        resource.resource_id
        for resource in runtime.resources.list_by_type(
            ResourceType.AVATAR_CHARACTER
        )
        if resource.visibility is ResourceVisibility.SYSTEM_PUBLIC
    }
    # 人物多半已是專案專屬：公開清單對 SDK 會是空的，帶 Embed key 的網站要能看到
    # 自己專案的人物。middleware 已驗過金鑰（含來源與路徑），這裡只讀結果。
    current = getattr(request.state, "current_account", None)
    if isinstance(current, CurrentAccount) and current.embed_key is not None:
        visible_ids |= _embed_project_character_ids(runtime, current.embed_key)
    return {
        "characters": [
            character
            for character in get_store().list_public_characters()
            if character["char_id"] in visible_ids
        ]
    }

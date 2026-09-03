"""Administrator CRUD for embed keys.

A key id is a public identifier, not a secret, so it is returned in full on
every read; the protection is the origin allowlist plus the per-key limits.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from .dependencies import CurrentAccount, require_admin
from .models import EmbedKeyRecord, ResourceType
from .repositories import (
    DEFAULT_DAILY_REQUEST_QUOTA,
    DEFAULT_RATE_LIMIT_PER_MINUTE,
    EmbedKeyNotFoundError,
)
from .runtime import AuthRuntime, get_auth_runtime

router = APIRouter(prefix="/api/v1/embed-keys", tags=["Embed Keys"])

_KEY_NOT_FOUND = "Embed key not found"
_PROJECT_NOT_FOUND = "Resource not found"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _normalize_origin(raw: str) -> str:
    """Accept only an exact `scheme://host[:port]`; a wildcard is refused."""
    origin = raw.strip()
    if not origin:
        raise HTTPException(status_code=400, detail="來源網域不可為空白")
    if "*" in origin:
        raise HTTPException(status_code=400, detail=f"來源網域不可使用萬用字元：{origin}")
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail=f"來源網域必須是 scheme://host[:port] 格式：{origin}",
        )
    # path/query/fragment 都不屬於 origin，出現就代表格式錯了。
    if parsed.path or parsed.query or parsed.fragment:
        raise HTTPException(
            status_code=400,
            detail=f"來源網域不可帶路徑或查詢字串：{origin}",
        )
    return f"{parsed.scheme}://{parsed.netloc}".casefold()


def _normalize_origins(raw_origins: list[str]) -> list[str]:
    origins = [_normalize_origin(origin) for origin in raw_origins]
    if not origins:
        raise HTTPException(status_code=400, detail="至少需要一個允許的來源網域")
    # 去重但保留輸入順序，避免同一個 origin 重複佔用列表。
    return list(dict.fromkeys(origins))


def _require_project(runtime: AuthRuntime, project_id: str) -> None:
    if runtime.resources.get(ResourceType.PROJECT, project_id.strip()) is None:
        raise HTTPException(status_code=404, detail=_PROJECT_NOT_FOUND)


class EmbedKeyCreateRequest(_StrictModel):
    label: str = ""
    project_id: str = Field(min_length=1)
    allowed_origins: list[str] = Field(min_length=1)
    default_character_id: str = ""
    allowed_character_ids: list[str] = Field(default_factory=list)
    default_persona_id: str = ""
    default_tts_provider: str = ""
    default_tts_voice: str = ""
    rate_limit_per_minute: int = Field(
        default=DEFAULT_RATE_LIMIT_PER_MINUTE,
        ge=1,
    )
    daily_request_quota: int = Field(default=DEFAULT_DAILY_REQUEST_QUOTA, ge=1)


class EmbedKeyUpdateRequest(_StrictModel):
    label: str | None = None
    allowed_origins: list[str] | None = None
    default_character_id: str | None = None
    allowed_character_ids: list[str] | None = None
    default_persona_id: str | None = None
    default_tts_provider: str | None = None
    default_tts_voice: str | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1)
    daily_request_quota: int | None = Field(default=None, ge=1)
    disabled: bool | None = None


def _serialize(record: EmbedKeyRecord, requests_today: int) -> dict[str, object]:
    return {
        "key_id": record.key_id,
        "label": record.label,
        "project_id": record.project_id,
        "allowed_origins": list(record.allowed_origins),
        "default_character_id": record.default_character_id,
        "allowed_character_ids": list(record.allowed_character_ids),
        "default_persona_id": record.default_persona_id,
        "default_tts_provider": record.default_tts_provider,
        "default_tts_voice": record.default_tts_voice,
        "rate_limit_per_minute": record.rate_limit_per_minute,
        "daily_request_quota": record.daily_request_quota,
        "disabled": record.disabled,
        "created_by": record.created_by,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "last_used_at": record.last_used_at,
        "requests_today": requests_today,
    }


@router.get("", summary="列出 Embed 金鑰")
async def list_embed_keys(
    _current: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, object]:
    records = runtime.embed_keys.list_all()
    return {
        "embed_keys": [
            _serialize(record, runtime.embed_keys.requests_today(record.key_id))
            for record in records
        ]
    }


@router.post("", status_code=status.HTTP_201_CREATED, summary="建立 Embed 金鑰")
async def create_embed_key(
    payload: EmbedKeyCreateRequest,
    current: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, object]:
    origins = _normalize_origins(payload.allowed_origins)
    _require_project(runtime, payload.project_id)
    try:
        record = runtime.embed_keys.create(
            label=payload.label,
            project_id=payload.project_id,
            allowed_origins=origins,
            default_character_id=payload.default_character_id,
            allowed_character_ids=payload.allowed_character_ids,
            default_persona_id=payload.default_persona_id,
            default_tts_provider=payload.default_tts_provider,
            default_tts_voice=payload.default_tts_voice,
            rate_limit_per_minute=payload.rate_limit_per_minute,
            daily_request_quota=payload.daily_request_quota,
            created_by=current.user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize(record, 0)


@router.patch("/{key_id}", summary="更新 Embed 金鑰")
async def update_embed_key(
    key_id: str,
    payload: EmbedKeyUpdateRequest,
    _current: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, object]:
    changes = payload.model_dump(exclude_none=True)
    if "allowed_origins" in changes:
        changes["allowed_origins"] = _normalize_origins(changes["allowed_origins"])
    try:
        record = runtime.embed_keys.update(key_id, **changes)
    except EmbedKeyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_KEY_NOT_FOUND) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize(record, runtime.embed_keys.requests_today(record.key_id))


@router.delete("/{key_id}", summary="刪除 Embed 金鑰")
async def delete_embed_key(
    key_id: str,
    _current: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, str]:
    try:
        runtime.embed_keys.delete(key_id)
    except EmbedKeyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_KEY_NOT_FOUND) from exc
    return {"status": "deleted", "key_id": key_id}

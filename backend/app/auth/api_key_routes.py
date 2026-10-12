"""Session-only management of account-owned integration credentials."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .api_keys_repository import ApiKeyNotFoundError
from .dependencies import AuthTransport, CurrentAccount, get_current_account
from .models import AccountType
from .policy import AccountPolicyError
from .repository_errors import UserNotFoundError
from .runtime import AuthRuntime, get_auth_runtime

router = APIRouter(prefix="/api/v1/api-keys", tags=["API Keys"])


class ApiKeyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=120)
    user_id: str | None = Field(default=None, min_length=1)
    expires_at: datetime | None = None

    @field_validator("expires_at", mode="before")
    @classmethod
    def require_iso_string(cls, value: object) -> object:
        if value is not None and not isinstance(value, str):
            raise ValueError("expires_at must be an ISO date string")
        if isinstance(value, str):
            datetime.fromisoformat(value)
        return value

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        return value


class ApiKeyResponse(BaseModel):
    key_id: str
    user_id: str
    label: str
    created_at: str
    expires_at: str | None
    revoked_at: str | None
    last_used_at: str | None
    request_count: int
    token_prefix: str


class ApiKeyListResponse(BaseModel):
    keys: list[ApiKeyResponse]


class ApiKeyCreatedResponse(ApiKeyResponse):
    key: str


class ApiKeyRevokedResponse(BaseModel):
    ok: bool


def require_key_management_session(
    response: Response,
    current: Annotated[CurrentAccount, Depends(get_current_account)],
) -> CurrentAccount:
    response.headers["Cache-Control"] = "no-store"
    if (
        current.transport not in {AuthTransport.BEARER, AuthTransport.COOKIE}
        or current.user.account_type is not AccountType.FORMAL
    ):
        raise HTTPException(
            status_code=403,
            detail="Account session required to manage API keys",
            headers={"Cache-Control": "no-store"},
        )
    return current


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, (ApiKeyNotFoundError, UserNotFoundError)):
        code = 404
        detail = "API key or account not found"
    elif isinstance(exc, AccountPolicyError):
        code = 403
        detail = "Account access denied"
    else:
        code = 400
        detail = str(exc)
    return HTTPException(
        status_code=code, detail=detail, headers={"Cache-Control": "no-store"}
    )


@router.get("", summary="列出帳號 API 金鑰", response_model=ApiKeyListResponse)
def list_api_keys(
    current: Annotated[
        CurrentAccount, Depends(require_key_management_session)
    ],
    runtime: Annotated[AuthRuntime, Depends(get_auth_runtime)],
    user_id: str | None = None,
) -> dict[str, object]:
    try:
        records = runtime.api_keys.list_for_user(
            actor_id=current.user.id, user_id=user_id or current.user.id
        )
    except (AccountPolicyError, UserNotFoundError) as exc:
        raise _error(exc) from exc
    return {"keys": [asdict(record) for record in records]}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="建立帳號 API 金鑰",
    response_model=ApiKeyCreatedResponse,
)
def create_api_key(
    payload: ApiKeyCreateRequest,
    current: Annotated[
        CurrentAccount, Depends(require_key_management_session)
    ],
    runtime: Annotated[AuthRuntime, Depends(get_auth_runtime)],
) -> dict[str, object]:
    try:
        record, credential = runtime.api_keys.create(
            actor_id=current.user.id,
            user_id=payload.user_id or current.user.id,
            label=payload.label,
            expires_at=payload.expires_at,
        )
    except (AccountPolicyError, UserNotFoundError, ValueError) as exc:
        raise _error(exc) from exc
    return {**asdict(record), "key": credential}


@router.delete(
    "/{key_id}",
    summary="撤銷帳號 API 金鑰",
    response_model=ApiKeyRevokedResponse,
)
def revoke_api_key(
    key_id: str,
    current: Annotated[
        CurrentAccount, Depends(require_key_management_session)
    ],
    runtime: Annotated[AuthRuntime, Depends(get_auth_runtime)],
) -> dict[str, bool]:
    try:
        runtime.api_keys.revoke(actor_id=current.user.id, key_id=key_id)
    except (AccountPolicyError, UserNotFoundError, ApiKeyNotFoundError) as exc:
        raise _error(exc) from exc
    return {"ok": True}

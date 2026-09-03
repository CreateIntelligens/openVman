"""Validate identity context injected by the trusted Backend facade."""

from __future__ import annotations

from dataclasses import dataclass
import hmac

from fastapi import Header, HTTPException

from config import get_settings

INTERNAL_TOKEN_HEADER = "X-Internal-Token"
USER_ID_HEADER = "X-OpenVMan-User-ID"
USER_ROLE_HEADER = "X-OpenVMan-Role"
PROJECT_ID_HEADER = "X-OpenVMan-Project-ID"
PRINCIPAL_TYPE_HEADER = "X-Principal-Type"
PRINCIPAL_ID_HEADER = "X-Principal-Id"


@dataclass(frozen=True, slots=True)
class TrustedRequestContext:
    user_id: str
    role: str
    project_id: str
    # Backend 沒帶主體標頭時（舊版本或內部呼叫）退回帳號主體，
    # 這樣帳本欄位永遠有值，不必在查詢端處理空字串。
    principal_type: str = "user"
    principal_id: str = ""


def require_internal_token(
    token: str = Header("", alias=INTERNAL_TOKEN_HEADER),
) -> None:
    expected = get_settings().gateway_internal_token
    if not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="invalid internal token")


def trusted_request_context(
    token: str = Header("", alias=INTERNAL_TOKEN_HEADER),
    user_id: str = Header("", alias=USER_ID_HEADER),
    role: str = Header("", alias=USER_ROLE_HEADER),
    project_id: str = Header("", alias=PROJECT_ID_HEADER),
    principal_type: str = Header("", alias=PRINCIPAL_TYPE_HEADER),
    principal_id: str = Header("", alias=PRINCIPAL_ID_HEADER),
) -> TrustedRequestContext:
    require_internal_token(token)
    if not user_id or not role or not project_id:
        raise HTTPException(status_code=403, detail="missing trusted request context")
    return TrustedRequestContext(
        user_id=user_id,
        role=role,
        project_id=project_id,
        principal_type=_header_value(principal_type) or "user",
        principal_id=_header_value(principal_id) or user_id,
    )


def _header_value(value: object) -> str:
    """Tolerate direct calls that omit the optional principal headers.

    FastAPI 只有在解析請求時才會把 Header() 預設值換成字串；程式碼直接
    呼叫這個函式時拿到的是 Header 物件本身，當成空值處理。
    """
    return value if isinstance(value, str) else ""

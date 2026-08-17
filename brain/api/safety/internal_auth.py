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


@dataclass(frozen=True, slots=True)
class TrustedRequestContext:
    user_id: str
    role: str
    project_id: str


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
) -> TrustedRequestContext:
    require_internal_token(token)
    if not user_id or not role or not project_id:
        raise HTTPException(status_code=403, detail="missing trusted request context")
    return TrustedRequestContext(
        user_id=user_id,
        role=role,
        project_id=project_id,
    )

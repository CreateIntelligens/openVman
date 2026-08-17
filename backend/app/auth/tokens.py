"""Strict HS256 session JWT issue and validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from .models import AccountRole, AccountType, UserRecord

_ALGORITHM = "HS256"
_REQUIRED_CLAIMS = ("sub", "role", "kind", "ver", "iat", "exp", "iss", "aud")


class AuthConfigurationError(RuntimeError):
    pass


class InvalidSessionTokenError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SessionClaims:
    subject: str
    role: AccountRole
    account_type: AccountType
    token_version: int
    issued_at: int
    expires_at: int


class SessionTokenService:
    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        audience: str,
        lifetime_seconds: int,
    ) -> None:
        if not secret:
            raise AuthConfigurationError("SESSION_JWT_SECRET is required")
        self._secret = secret
        self._issuer = issuer
        self._audience = audience
        self.lifetime_seconds = lifetime_seconds

    def issue(
        self,
        user: UserRecord,
        *,
        now: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> str:
        issued_at = now or datetime.now(timezone.utc)
        session_expires_at = issued_at + timedelta(seconds=self.lifetime_seconds)
        if expires_at is not None:
            expiry_cap = expires_at
            if expiry_cap.tzinfo is None:
                expiry_cap = expiry_cap.replace(tzinfo=timezone.utc)
            session_expires_at = min(session_expires_at, expiry_cap)
        if session_expires_at <= issued_at:
            raise ValueError("session expiry must be later than issue time")
        payload = {
            "sub": user.id,
            "role": user.role.value,
            "kind": user.account_type.value,
            "ver": user.token_version,
            "iat": int(issued_at.timestamp()),
            "exp": int(session_expires_at.timestamp()),
            "iss": self._issuer,
            "aud": self._audience,
        }
        return jwt.encode(payload, self._secret, algorithm=_ALGORITHM)

    def decode(self, token: str) -> SessionClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[_ALGORITHM],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": list(_REQUIRED_CLAIMS)},
            )
            subject = payload["sub"]
            role = payload["role"]
            kind = payload["kind"]
            token_version = payload["ver"]
            issued_at = payload["iat"]
            expires_at = payload["exp"]
            if not isinstance(subject, str) or not subject:
                raise TypeError("sub must be a non-empty string")
            if isinstance(token_version, bool) or not isinstance(token_version, int):
                raise TypeError("ver must be an integer")
            if token_version < 0:
                raise ValueError("ver must not be negative")
            if isinstance(issued_at, bool) or not isinstance(issued_at, int):
                raise TypeError("iat must be an integer")
            if isinstance(expires_at, bool) or not isinstance(expires_at, int):
                raise TypeError("exp must be an integer")
            account_role = AccountRole(role)
            account_type = AccountType(kind)
        except (KeyError, TypeError, ValueError, jwt.PyJWTError) as exc:
            raise InvalidSessionTokenError("invalid session token") from exc

        return SessionClaims(
            subject=subject,
            role=account_role,
            account_type=account_type,
            token_version=token_version,
            issued_at=issued_at,
            expires_at=expires_at,
        )

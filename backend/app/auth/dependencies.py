"""FastAPI authentication, authorization, and cookie CSRF dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, WebSocket, status
from starlette.requests import HTTPConnection

from .models import AccountRole, AccountType, TemporaryCredentialRecord, UserRecord
from .runtime import AuthRuntime, get_auth_runtime
from .tokens import InvalidSessionTokenError

_SESSION_COOKIE_NAME = "openvman_session"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_INVALID_SESSION_DETAIL = "Invalid or expired session"


class AuthTransport(StrEnum):
    BEARER = "bearer"
    COOKIE = "cookie"


@dataclass(frozen=True, slots=True)
class CurrentAccount:
    user: UserRecord
    transport: AuthTransport
    temporary_credential: TemporaryCredentialRecord | None = None


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_INVALID_SESSION_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _extract_bearer(connection: HTTPConnection) -> str | None:
    authorization = connection.headers.get("authorization")
    if authorization is None:
        return None
    scheme, separator, value = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not separator or not value.strip():
        raise _unauthorized()
    return value.strip()


def _request_origin(connection: HTTPConnection) -> tuple[str, str]:
    forwarded_proto = connection.headers.get("x-forwarded-proto", "")
    scheme = forwarded_proto.split(",", maxsplit=1)[0].strip() or connection.url.scheme
    scheme = {"ws": "http", "wss": "https"}.get(scheme.casefold(), scheme)
    return scheme.casefold(), connection.headers.get("host", "").casefold()


def enforce_same_origin(connection: HTTPConnection) -> None:
    origin = connection.headers.get("origin")
    if not origin:
        raise HTTPException(status_code=403, detail="Same-origin request required")
    parsed = urlsplit(origin)
    request_scheme, request_host = _request_origin(connection)
    if (
        parsed.scheme.casefold() != request_scheme
        or parsed.netloc.casefold() != request_host
    ):
        raise HTTPException(status_code=403, detail="Same-origin request required")


def _authenticate_connection(
    connection: HTTPConnection,
    runtime: AuthRuntime,
    *,
    require_cookie_origin: bool,
) -> CurrentAccount:
    bearer = _extract_bearer(connection)
    if bearer is not None:
        token = bearer
        transport = AuthTransport.BEARER
    else:
        token = connection.cookies.get(_SESSION_COOKIE_NAME, "")
        transport = AuthTransport.COOKIE
    if not token:
        raise _unauthorized()

    try:
        claims = runtime.tokens.decode(token)
    except InvalidSessionTokenError as exc:
        raise _unauthorized() from exc

    user = runtime.users.get_by_id(claims.subject)
    if (
        user is None
        or user.disabled
        or user.role is not claims.role
        or user.account_type is not claims.account_type
        or user.token_version != claims.token_version
    ):
        raise _unauthorized()

    if transport is AuthTransport.COOKIE and require_cookie_origin:
        enforce_same_origin(connection)

    temporary_credential = None
    if user.account_type is AccountType.TEMPORARY:
        temporary_credential = runtime.temporary_accounts.get_credential_for_user(
            user.id
        )
        if temporary_credential is None or temporary_credential.expires_at is None:
            raise _unauthorized()
        try:
            expires_at = datetime.fromisoformat(temporary_credential.expires_at)
        except ValueError as exc:
            raise _unauthorized() from exc
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            raise _unauthorized()

    current = CurrentAccount(
        user=user,
        transport=transport,
        temporary_credential=temporary_credential,
    )
    connection.state.current_account = current
    return current


def authenticate_request(request: Request, runtime: AuthRuntime) -> CurrentAccount:
    return _authenticate_connection(
        request,
        runtime,
        require_cookie_origin=request.method not in _SAFE_METHODS,
    )


def authenticate_websocket(
    websocket: WebSocket,
    runtime: AuthRuntime,
) -> CurrentAccount:
    """Authenticate a WebSocket before accept; cookie upgrades must be same-origin."""
    return _authenticate_connection(
        websocket,
        runtime,
        require_cookie_origin=not bool(_extract_bearer(websocket)),
    )


def get_current_account(
    request: Request,
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> CurrentAccount:
    existing = getattr(request.state, "current_account", None)
    if isinstance(existing, CurrentAccount):
        return existing
    return authenticate_request(request, runtime)


def require_admin(
    current: CurrentAccount = Depends(get_current_account),
) -> CurrentAccount:
    if current.user.role is not AccountRole.ADMIN:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return current

"""Login, session profile, and password APIs."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from .account_schemas import AccountProfile, _StrictModel
from .dependencies import (
    AuthTransport,
    CurrentAccount,
    get_current_account,
    require_admin_portal_access,
)
from .models import AccountType, has_admin_portal_access
from .passwords import PasswordValidationError, hash_password, verify_password
from .policy import AccountPolicyError
from .runtime import AuthRuntime, get_auth_runtime
from .temporary_accounts_repository import (
    TemporaryCredentialExpiredError,
    TemporaryCredentialNotFoundError,
)

_SESSION_COOKIE_NAME = "openvman_session"
_INVALID_CREDENTIALS = "Invalid credentials"
_DUMMY_PASSWORD_HASH = "$2b$12$RHUg9KKg90SMUGjfwS3QxeboW/TeCDDpAZQBOcOOnOfYB64TsIfGO"
_TEMPORARY_PASSWORD_PATTERN = re.compile(
    r"\A(?:(?P<locator>[A-Za-z0-9]{12})[A-Za-z0-9]{8}"
    r"|(?P<legacy_locator>[A-Za-z0-9]{12}))\Z"
)

auth_router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class LoginRequest(_StrictModel):
    username: str
    password: str


class TemporaryLoginRequest(_StrictModel):
    password: str


class VerifyPasswordRequest(_StrictModel):
    password: str


class ChangeOwnPasswordRequest(_StrictModel):
    current_password: str
    new_password: str


class LoginResponse(_StrictModel):
    account: AccountProfile
    token: str


class LogoutResponse(_StrictModel):
    ok: bool


def _set_session_cookie(
    response: Response,
    token: str,
    runtime: AuthRuntime,
    *,
    max_age: int | None = None,
) -> None:
    response.set_cookie(
        key=_SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age or runtime.tokens.lifetime_seconds,
        httponly=True,
        secure=runtime.config.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response, runtime: AuthRuntime) -> None:
    response.delete_cookie(
        key=_SESSION_COOKIE_NAME,
        httponly=True,
        secure=runtime.config.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def _formal_login(
    body: LoginRequest,
    response: Response,
    runtime: AuthRuntime,
    *,
    require_portal_access: bool,
) -> LoginResponse:
    user = runtime.users.get_by_username(body.username)
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_matches = verify_password(body.password, password_hash)
    if (
        user is None
        or user.account_type is not AccountType.FORMAL
        or user.disabled
        or not password_matches
    ):
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS)
    if require_portal_access and not has_admin_portal_access(user):
        raise HTTPException(
            status_code=403,
            detail="此帳號沒有進入管理後台的權限",
        )

    runtime.users.record_login(user.id, now=datetime.now(timezone.utc))
    token = runtime.tokens.issue(user)
    _set_session_cookie(response, token, runtime)
    return LoginResponse(
        account=AccountProfile.from_record(user, runtime=runtime),
        token=token,
    )


@auth_router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    response: Response,
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> LoginResponse:
    return _formal_login(
        body,
        response,
        runtime,
        require_portal_access=False,
    )


@auth_router.post("/admin-login", response_model=LoginResponse)
def admin_login(
    body: LoginRequest,
    response: Response,
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> LoginResponse:
    return _formal_login(
        body,
        response,
        runtime,
        require_portal_access=True,
    )


def _temporary_login(
    body: TemporaryLoginRequest,
    response: Response,
    runtime: AuthRuntime,
    *,
    require_portal_access: bool,
) -> LoginResponse:
    match = _TEMPORARY_PASSWORD_PATTERN.fullmatch(body.password)
    located = (
        runtime.temporary_accounts.get_credential_by_locator(
            match.group("locator") or match.group("legacy_locator")
        )
        if match is not None
        else None
    )
    user = located[0] if located is not None else None
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_matches = verify_password(body.password, password_hash)
    if user is None or not password_matches:
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS)
    if require_portal_access and not has_admin_portal_access(user):
        raise HTTPException(
            status_code=403,
            detail="此帳號沒有進入管理後台的權限",
        )

    now = datetime.now(timezone.utc)
    try:
        user, credential = runtime.temporary_accounts.activate(
            user_id=user.id,
            now=now,
        )
    except TemporaryCredentialExpiredError as exc:
        raise HTTPException(
            status_code=401,
            detail="此批次已過期或被撤銷",
        ) from exc
    except TemporaryCredentialNotFoundError as exc:
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS) from exc

    runtime.users.record_login(user.id, now=now)
    expires_at = datetime.fromisoformat(credential.expires_at or "")
    remaining_seconds = max(1, ceil((expires_at - now).total_seconds()))
    token = runtime.tokens.issue(user, now=now, expires_at=expires_at)
    _set_session_cookie(
        response,
        token,
        runtime,
        max_age=min(runtime.tokens.lifetime_seconds, remaining_seconds),
    )
    return LoginResponse(
        account=AccountProfile.from_record(
            user,
            runtime=runtime,
            credential=credential,
            now=now,
        ),
        token=token,
    )


@auth_router.post("/temporary-login", response_model=LoginResponse)
def temporary_login(
    body: TemporaryLoginRequest,
    response: Response,
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> LoginResponse:
    return _temporary_login(
        body,
        response,
        runtime,
        require_portal_access=False,
    )


@auth_router.post("/admin-temporary-login", response_model=LoginResponse)
def admin_temporary_login(
    body: TemporaryLoginRequest,
    response: Response,
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> LoginResponse:
    return _temporary_login(
        body,
        response,
        runtime,
        require_portal_access=True,
    )


@auth_router.post("/logout", response_model=LogoutResponse)
def logout(
    response: Response,
    _current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> LogoutResponse:
    _clear_session_cookie(response, runtime)
    return LogoutResponse(ok=True)


@auth_router.get("/me", response_model=AccountProfile)
def me(
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AccountProfile:
    return AccountProfile.from_record(
        current.user,
        runtime=runtime,
        credential=current.temporary_credential,
    )


class SessionResponse(_StrictModel):
    account: AccountProfile | None


@auth_router.get("/session", response_model=SessionResponse)
def session(
    request: Request,
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> SessionResponse:
    # 沒登入是開頁時的正常狀態，不是錯誤：回 200，瀏覽器才不會在 console 印紅字。
    try:
        current = get_current_account(request, runtime)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_401_UNAUTHORIZED:
            raise
        return SessionResponse(account=None)
    return SessionResponse(
        account=AccountProfile.from_record(
            current.user,
            runtime=runtime,
            credential=current.temporary_credential,
        ),
    )


@auth_router.get("/admin-me", response_model=AccountProfile)
def admin_me(
    current: CurrentAccount = Depends(require_admin_portal_access),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AccountProfile:
    return AccountProfile.from_record(
        current.user,
        runtime=runtime,
        credential=current.temporary_credential,
    )


_PASSWORD_MISMATCH = "密碼不正確"
_TOO_MANY_PASSWORD_ATTEMPTS = "嘗試太多次，請稍後再試"


@auth_router.post(
    "/verify-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="確認目前帳號的密碼（展示機台解鎖設定用）",
)
def verify_current_password(
    body: VerifyPasswordRequest,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> Response:
    """Check the password of the signed-in account without touching the session.

    打錯回 400 而不是 401：前台把 401 當成 session 失效並登出，現場人員打錯
    一次就會把展示機台登出。臨時帳號的 password_hash 就是它的臨時密碼雜湊，
    所以兩種帳號走同一條比對。
    """
    if current.transport is AuthTransport.EMBED_KEY:
        raise HTTPException(status_code=403, detail="此身分沒有可驗證的密碼")
    limiter = runtime.password_verify_attempts
    key = current.user.id
    retry_after = limiter.retry_after(key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=_TOO_MANY_PASSWORD_ATTEMPTS,
            headers={"Retry-After": str(retry_after)},
        )
    if not verify_password(body.password, current.user.password_hash):
        limiter.record_failure(key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_PASSWORD_MISMATCH,
        )
    limiter.reset(key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.post("/password", response_model=LoginResponse)
def change_own_password(
    body: ChangeOwnPasswordRequest,
    response: Response,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> LoginResponse:
    if not verify_password(body.current_password, current.user.password_hash):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    try:
        user = runtime.users.change_own_password(
            user_id=current.user.id,
            password_hash=hash_password(body.new_password),
        )
    except AccountPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PasswordValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    token = runtime.tokens.issue(user)
    _set_session_cookie(response, token, runtime)
    return LoginResponse(
        account=AccountProfile.from_record(user, runtime=runtime),
        token=token,
    )

"""Login, session profile, and administrator-managed account APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
import re
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from .dependencies import CurrentAccount, get_current_account, require_admin
from .models import (
    AccountDefaultsRecord,
    AccountRole,
    AccountType,
    ResourceGrantRecord,
    ResourceType,
    TemporaryCredentialRecord,
    UserRecord,
)
from .passwords import PasswordValidationError, hash_password, verify_password
from .repositories import (
    AccountEnabledError,
    InvalidResourceGrantError,
    LastAdminError,
    OwnedResourcesError,
    SelfProtectionError,
    TemporaryBatch,
    TemporaryBatchAccount,
    TemporaryCredentialCreate,
    TemporaryCredentialExpiredError,
    TemporaryCredentialNotFoundError,
    UserNotFoundError,
    UsernameConflictError,
)
from .runtime import AuthRuntime, get_auth_runtime

_SESSION_COOKIE_NAME = "openvman_session"
_INVALID_CREDENTIALS = "Invalid credentials"
_DUMMY_PASSWORD_HASH = "$2b$12$RHUg9KKg90SMUGjfwS3QxeboW/TeCDDpAZQBOcOOnOfYB64TsIfGO"
_TEMPORARY_PASSWORD_PATTERN = re.compile(r"\A([A-Za-z0-9]{4})[A-Za-z0-9]{8}\Z")
_TEMPORARY_DURATION_SECONDS = 72 * 60 * 60
_TEMPORARY_PASSWORD_ALPHABET = string.ascii_letters + string.digits
_TEMPORARY_PASSWORD_LENGTH = 12
_TEMPORARY_LOCATOR_LENGTH = 4

auth_router = APIRouter(prefix="/api/auth", tags=["Authentication"])
users_router = APIRouter(prefix="/api/users", tags=["Accounts"])
temporary_accounts_router = APIRouter(
    prefix="/api/temporary-accounts",
    tags=["Temporary accounts"],
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountDefaultsProfile(_StrictModel):
    project_id: str
    character_id: str
    voice_provider: str
    voice_id: str

    @classmethod
    def from_record(cls, record: AccountDefaultsRecord) -> "AccountDefaultsProfile":
        return cls(
            project_id=record.project_id,
            character_id=record.character_id,
            voice_provider=record.voice_provider,
            voice_id=record.voice_id,
        )


class AccountProfile(_StrictModel):
    id: str
    username: str
    role: AccountRole
    kind: AccountType
    disabled: bool
    created_at: str
    created_by: str | None
    expires_at: str | None = None
    remaining_seconds: int | None = None
    defaults: AccountDefaultsProfile | None = None

    @classmethod
    def from_record(
        cls,
        user: UserRecord,
        *,
        runtime: AuthRuntime | None = None,
        credential: TemporaryCredentialRecord | None = None,
        now: datetime | None = None,
    ) -> "AccountProfile":
        defaults = runtime.temporary_accounts.get_defaults(user.id) if runtime else None
        expires_at = credential.expires_at if credential is not None else None
        remaining_seconds = None
        if expires_at is not None:
            current_time = now or datetime.now(timezone.utc)
            remaining_seconds = max(
                0,
                ceil(
                    (
                        datetime.fromisoformat(expires_at)
                        - current_time.astimezone(timezone.utc)
                    ).total_seconds()
                ),
            )
        return cls(
            id=user.id,
            username=user.username,
            role=user.role,
            kind=user.account_type,
            disabled=user.disabled,
            created_at=user.created_at,
            created_by=user.created_by,
            expires_at=expires_at,
            remaining_seconds=remaining_seconds,
            defaults=(
                AccountDefaultsProfile.from_record(defaults)
                if defaults is not None
                else None
            ),
        )


class AdminAccountProfile(AccountProfile):
    resource_counts: dict[str, int]

    @classmethod
    def from_record(
        cls,
        user: UserRecord,
        runtime: AuthRuntime,
    ) -> "AdminAccountProfile":
        return cls(
            **AccountProfile.from_record(user, runtime=runtime).model_dump(),
            resource_counts=runtime.resources.count_private_by_owner(user.id),
        )


class LoginRequest(_StrictModel):
    username: str
    password: str


class TemporaryLoginRequest(_StrictModel):
    password: str


class LoginResponse(_StrictModel):
    account: AccountProfile
    token: str


class CreateAccountRequest(_StrictModel):
    username: str
    password: str
    role: AccountRole = AccountRole.USER


class SetDisabledRequest(_StrictModel):
    disabled: bool


class LogoutResponse(_StrictModel):
    ok: bool


class TemporaryBatchGrants(_StrictModel):
    projects: list[str] = Field(min_length=1)
    avatar_characters: list[str] = Field(min_length=1)
    custom_voices: list[str] = Field(min_length=1)


class CreateTemporaryBatchRequest(_StrictModel):
    grants: TemporaryBatchGrants
    defaults: AccountDefaultsProfile


class TemporaryCredentialCreated(_StrictModel):
    user_id: str
    password: str
    expires_at: None = None


class TemporaryBatchCreated(_StrictModel):
    batch_id: str
    credentials: list[TemporaryCredentialCreated]
    created_at: str


class ResourceGrantProfile(_StrictModel):
    resource_type: ResourceType
    resource_id: str

    @classmethod
    def from_record(cls, record: ResourceGrantRecord) -> "ResourceGrantProfile":
        return cls(
            resource_type=record.resource_type,
            resource_id=record.resource_id,
        )


class TemporaryAccountAudit(_StrictModel):
    user_id: str
    username: str
    state: str
    disabled: bool
    first_used_at: str | None
    expires_at: str | None
    remaining_seconds: int | None
    grants: list[ResourceGrantProfile]
    defaults: AccountDefaultsProfile


class TemporaryBatchAudit(_StrictModel):
    batch_id: str
    created_by: str | None
    created_at: str
    revoked_at: str | None
    state: str
    first_used_at: str | None
    expires_at: str | None
    account_count: int
    grants: TemporaryBatchGrants
    defaults: AccountDefaultsProfile
    accounts: list[TemporaryAccountAudit]


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


@auth_router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    response: Response,
    runtime: AuthRuntime = Depends(get_auth_runtime),
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

    token = runtime.tokens.issue(user)
    _set_session_cookie(response, token, runtime)
    return LoginResponse(
        account=AccountProfile.from_record(user, runtime=runtime),
        token=token,
    )


@auth_router.post("/temporary-login", response_model=LoginResponse)
def temporary_login(
    body: TemporaryLoginRequest,
    response: Response,
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> LoginResponse:
    match = _TEMPORARY_PASSWORD_PATTERN.fullmatch(body.password)
    located = (
        runtime.temporary_accounts.get_credential_by_locator(match.group(1))
        if match is not None
        else None
    )
    user = located[0] if located is not None else None
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_matches = verify_password(body.password, password_hash)
    if user is None or not password_matches:
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS)

    now = datetime.now(timezone.utc)
    try:
        user, credential = runtime.temporary_accounts.activate(
            user_id=user.id,
            now=now,
        )
    except (TemporaryCredentialExpiredError, TemporaryCredentialNotFoundError) as exc:
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS) from exc

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


def _new_temporary_password() -> tuple[str, str]:
    password = "".join(
        secrets.choice(_TEMPORARY_PASSWORD_ALPHABET)
        for _ in range(_TEMPORARY_PASSWORD_LENGTH)
    )
    return password[:_TEMPORARY_LOCATOR_LENGTH], password


def _temporary_account_state(
    account: TemporaryBatchAccount,
    now: datetime,
) -> str:
    if account.user.disabled:
        return "revoked"
    if account.credential.first_used_at is None:
        return "unused"
    expires_at = datetime.fromisoformat(account.credential.expires_at or "")
    return "expired" if expires_at <= now else "active"


def _temporary_account_audit(
    account: TemporaryBatchAccount,
    now: datetime,
) -> TemporaryAccountAudit:
    expires_at = account.credential.expires_at
    remaining_seconds = None
    if expires_at is not None:
        remaining_seconds = max(
            0,
            ceil((datetime.fromisoformat(expires_at) - now).total_seconds()),
        )
    return TemporaryAccountAudit(
        user_id=account.user.id,
        username=account.user.username,
        state=_temporary_account_state(account, now),
        disabled=account.user.disabled,
        first_used_at=account.credential.first_used_at,
        expires_at=expires_at,
        remaining_seconds=remaining_seconds,
        grants=[ResourceGrantProfile.from_record(grant) for grant in account.grants],
        defaults=AccountDefaultsProfile.from_record(account.defaults),
    )


def _temporary_batch_audit(
    batch: TemporaryBatch,
    *,
    now: datetime | None = None,
) -> TemporaryBatchAudit:
    current_time = now or datetime.now(timezone.utc)
    accounts = [
        _temporary_account_audit(account, current_time) for account in batch.accounts
    ]
    states = {account.state for account in accounts}
    if batch.batch.revoked_at is not None or states == {"revoked"}:
        state = "revoked"
    elif "active" in states:
        state = "active"
    elif "unused" in states:
        state = "unused"
    else:
        state = "expired"

    first_used_values = [
        account.first_used_at
        for account in accounts
        if account.first_used_at is not None
    ]
    expires_values = [
        account.expires_at for account in accounts if account.expires_at is not None
    ]
    first_account = batch.accounts[0]
    grant_values: dict[ResourceType, list[str]] = {
        ResourceType.PROJECT: [],
        ResourceType.AVATAR_CHARACTER: [],
        ResourceType.CUSTOM_VOICE: [],
    }
    for grant in first_account.grants:
        if grant.resource_type in grant_values:
            grant_values[grant.resource_type].append(grant.resource_id)
    return TemporaryBatchAudit(
        batch_id=batch.batch.id,
        created_by=batch.batch.created_by,
        created_at=batch.batch.created_at,
        revoked_at=batch.batch.revoked_at,
        state=state,
        first_used_at=min(first_used_values) if first_used_values else None,
        expires_at=max(expires_values) if expires_values else None,
        account_count=len(accounts),
        grants=TemporaryBatchGrants(
            projects=grant_values[ResourceType.PROJECT],
            avatar_characters=grant_values[ResourceType.AVATAR_CHARACTER],
            custom_voices=grant_values[ResourceType.CUSTOM_VOICE],
        ),
        defaults=AccountDefaultsProfile.from_record(first_account.defaults),
        accounts=accounts,
    )


@temporary_accounts_router.post(
    "/batches",
    response_model=TemporaryBatchCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_temporary_batch(
    body: CreateTemporaryBatchRequest,
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> TemporaryBatchCreated:
    generated: list[tuple[str, str]] = []
    seen_locators: set[str] = set()
    while len(generated) < 5:
        locator, password = _new_temporary_password()
        if (
            locator in seen_locators
            or runtime.temporary_accounts.get_credential_by_locator(locator)
            is not None
        ):
            continue
        seen_locators.add(locator)
        generated.append((locator, password))

    credentials = [
        TemporaryCredentialCreate(
            locator=locator,
            password_hash=hash_password(password),
        )
        for locator, password in generated
    ]
    grants = [
        *((ResourceType.PROJECT, value) for value in body.grants.projects),
        *(
            (ResourceType.AVATAR_CHARACTER, value)
            for value in body.grants.avatar_characters
        ),
        *((ResourceType.CUSTOM_VOICE, value) for value in body.grants.custom_voices),
    ]
    try:
        batch = runtime.temporary_accounts.create_batch(
            created_by=admin.user.id,
            credentials=credentials,
            grants=grants,
            defaults=(
                body.defaults.project_id,
                body.defaults.character_id,
                body.defaults.voice_provider,
                body.defaults.voice_id,
            ),
            duration_seconds=_TEMPORARY_DURATION_SECONDS,
        )
    except (InvalidResourceGrantError, UserNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    user_by_locator = {
        account.credential.code_locator: account.user.id for account in batch.accounts
    }
    return TemporaryBatchCreated(
        batch_id=batch.batch.id,
        credentials=[
            TemporaryCredentialCreated(
                user_id=user_by_locator[locator],
                password=password,
            )
            for locator, password in generated
        ],
        created_at=batch.batch.created_at,
    )


@temporary_accounts_router.get(
    "/batches",
    response_model=list[TemporaryBatchAudit],
)
def list_temporary_batches(
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> list[TemporaryBatchAudit]:
    now = datetime.now(timezone.utc)
    return [
        _temporary_batch_audit(batch, now=now)
        for batch in runtime.temporary_accounts.list_batches()
    ]


@temporary_accounts_router.post(
    "/batches/{batch_id}/revoke",
    response_model=TemporaryBatchAudit,
)
def revoke_temporary_batch(
    batch_id: str,
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> TemporaryBatchAudit:
    try:
        batch = runtime.temporary_accounts.revoke_batch(batch_id)
    except TemporaryCredentialNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Temporary batch not found"
        ) from exc
    return _temporary_batch_audit(batch)


@users_router.get("", response_model=list[AdminAccountProfile])
def list_accounts(
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> list[AdminAccountProfile]:
    return [
        AdminAccountProfile.from_record(user, runtime) for user in runtime.users.list()
    ]


@users_router.post(
    "",
    response_model=AdminAccountProfile,
    status_code=status.HTTP_201_CREATED,
)
def create_account(
    body: CreateAccountRequest,
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AdminAccountProfile:
    try:
        password_hash = hash_password(body.password)
        user = runtime.users.create(
            username=body.username,
            password_hash=password_hash,
            role=body.role,
            created_by=admin.user.id,
        )
    except (PasswordValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UsernameConflictError as exc:
        raise HTTPException(status_code=409, detail="Username already exists") from exc
    return AdminAccountProfile.from_record(user, runtime)


@users_router.patch("/{user_id}/disabled", response_model=AdminAccountProfile)
def set_account_disabled(
    user_id: str,
    body: SetDisabledRequest,
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AdminAccountProfile:
    try:
        user = runtime.users.set_disabled_guarded(
            actor_id=admin.user.id,
            user_id=user_id,
            disabled=body.disabled,
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc
    except (LastAdminError, SelfProtectionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AdminAccountProfile.from_record(user, runtime)


@users_router.post("/{user_id}/revoke", response_model=AdminAccountProfile)
def revoke_account_sessions(
    user_id: str,
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AdminAccountProfile:
    try:
        user = runtime.users.revoke_sessions(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc
    return AdminAccountProfile.from_record(user, runtime)


@users_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    user_id: str,
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> Response:
    try:
        runtime.users.delete_guarded(actor_id=admin.user.id, user_id=user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc
    except OwnedResourcesError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Account owns private resources",
                "resource_counts": exc.counts,
            },
        ) from exc
    except (AccountEnabledError, LastAdminError, SelfProtectionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Routes for administrator-managed temporary account batches."""

from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import Field

from .dependencies import CurrentAccount, require_admin
from .models import AccountRole
from .passwords import hash_password
from .policy import AccountPolicyError
from .repositories import (
    InvalidResourceGrantError,
    TemporaryBatch,
    TemporaryBatchAccount,
    TemporaryCredentialCreate,
    TemporaryCredentialNotFoundError,
    UserNotFoundError,
)
from .routes import (
    AccountDefaultsProfile,
    AccountResourceGrants,
    ResourceGrantProfile,
    _StrictModel,
    _defaults_tuple,
    _resource_grants,
)
from .runtime import AuthRuntime, get_auth_runtime
from .temporary_passwords import TemporaryPasswordCipher

_TEMPORARY_DURATION_SECONDS = 72 * 60 * 60
_TEMPORARY_PASSWORD_ALPHABET = string.ascii_letters + string.digits
_TEMPORARY_PASSWORD_LENGTH = 20
_TEMPORARY_LOCATOR_LENGTH = 12

temporary_accounts_router = APIRouter(
    prefix="/api/v1/temporary-accounts",
    tags=["Temporary accounts"],
)


class CreateTemporaryBatchRequest(_StrictModel):
    grants: AccountResourceGrants
    defaults: AccountDefaultsProfile
    admin_portal_access: bool = False


class SetAdminPortalAccessRequest(_StrictModel):
    enabled: bool


class TemporaryCredentialCreated(_StrictModel):
    user_id: str
    password: str
    expires_at: None = None


class TemporaryBatchCreated(_StrictModel):
    batch_id: str
    credentials: list[TemporaryCredentialCreated]
    created_at: str
    admin_portal_access: bool


class TemporaryAccountAudit(_StrictModel):
    user_id: str
    username: str
    password: str | None = Field(default=None, repr=False)
    state: str
    disabled: bool
    first_used_at: str | None
    expires_at: str | None
    remaining_seconds: int | None
    grants: list[ResourceGrantProfile]
    defaults: AccountDefaultsProfile
    admin_portal_access: bool


class TemporaryBatchAudit(_StrictModel):
    batch_id: str
    created_by: str | None
    created_at: str
    revoked_at: str | None
    state: str
    first_used_at: str | None
    expires_at: str | None
    account_count: int
    grants: AccountResourceGrants
    defaults: AccountDefaultsProfile
    accounts: list[TemporaryAccountAudit]
    admin_portal_access: bool


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
    passwords: TemporaryPasswordCipher,
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
        password=passwords.decrypt(
            account.credential.password_ciphertext,
            account.credential.code_locator,
        ),
        state=_temporary_account_state(account, now),
        disabled=account.user.disabled,
        first_used_at=account.credential.first_used_at,
        expires_at=expires_at,
        remaining_seconds=remaining_seconds,
        grants=[ResourceGrantProfile.from_record(grant) for grant in account.grants],
        defaults=AccountDefaultsProfile.from_record(account.defaults),
        admin_portal_access=account.user.admin_portal_access,
    )


def _temporary_batch_audit(
    batch: TemporaryBatch,
    *,
    passwords: TemporaryPasswordCipher,
    now: datetime | None = None,
) -> TemporaryBatchAudit:
    current_time = now or datetime.now(timezone.utc)
    accounts = [
        _temporary_account_audit(account, current_time, passwords)
        for account in batch.accounts
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
    return TemporaryBatchAudit(
        batch_id=batch.batch.id,
        created_by=batch.batch.created_by,
        created_at=batch.batch.created_at,
        revoked_at=batch.batch.revoked_at,
        state=state,
        first_used_at=min(first_used_values) if first_used_values else None,
        expires_at=max(expires_values) if expires_values else None,
        account_count=len(accounts),
        grants=AccountResourceGrants.from_records(first_account.grants),
        defaults=AccountDefaultsProfile.from_record(first_account.defaults),
        accounts=accounts,
        admin_portal_access=first_account.user.admin_portal_access,
    )


@temporary_accounts_router.post(
    "/batches",
    response_model=TemporaryBatchCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_temporary_batch(
    body: CreateTemporaryBatchRequest,
    response: Response,
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> TemporaryBatchCreated:
    response.headers["Cache-Control"] = "no-store"
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
            password_ciphertext=runtime.temporary_passwords.encrypt(
                password, locator,
            ),
        )
        for locator, password in generated
    ]
    try:
        batch = runtime.temporary_accounts.create_batch(
            created_by=admin.user.id,
            credentials=credentials,
            grants=_resource_grants(body.grants),
            defaults=_defaults_tuple(body.defaults),
            duration_seconds=_TEMPORARY_DURATION_SECONDS,
            admin_portal_access=body.admin_portal_access,
        )
    except AccountPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
        admin_portal_access=body.admin_portal_access,
    )


@temporary_accounts_router.get(
    "/batches",
    response_model=list[TemporaryBatchAudit],
)
def list_temporary_batches(
    response: Response,
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> list[TemporaryBatchAudit]:
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(timezone.utc)
    # 與 list_accounts 同一條可見規則：ROOT 看全部，admin 只看自己的子樹。
    visible_to = None if admin.user.role is AccountRole.ROOT else admin.user.id
    return [
        _temporary_batch_audit(
            batch, passwords=runtime.temporary_passwords, now=now,
        )
        for batch in runtime.temporary_accounts.list_batches(visible_to=visible_to)
    ]


@temporary_accounts_router.patch(
    "/batches/{batch_id}/admin-portal-access",
    response_model=TemporaryBatchAudit,
)
def set_temporary_batch_admin_portal_access(
    batch_id: str,
    response: Response,
    body: SetAdminPortalAccessRequest,
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> TemporaryBatchAudit:
    try:
        batch = runtime.temporary_accounts.set_admin_portal_access(
            batch_id,
            actor_id=admin.user.id,
            enabled=body.enabled,
        )
    except TemporaryCredentialNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Temporary batch not found",
        ) from exc
    response.headers["Cache-Control"] = "no-store"
    return _temporary_batch_audit(batch, passwords=runtime.temporary_passwords)


@temporary_accounts_router.post(
    "/batches/{batch_id}/revoke",
    response_model=TemporaryBatchAudit,
)
def revoke_temporary_batch(
    batch_id: str,
    response: Response,
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> TemporaryBatchAudit:
    try:
        batch = runtime.temporary_accounts.revoke_batch(
            batch_id,
            actor_id=admin.user.id,
        )
    except TemporaryCredentialNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Temporary batch not found"
        ) from exc
    response.headers["Cache-Control"] = "no-store"
    return _temporary_batch_audit(batch, passwords=runtime.temporary_passwords)

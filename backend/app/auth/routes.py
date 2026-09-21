"""Login, session profile, and administrator-managed account APIs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_tts_config

from .dependencies import (
    CurrentAccount,
    get_current_account,
    require_admin,
    require_admin_portal_access,
    require_root,
)
from .models import (
    AccountDefaultsRecord,
    AccountRole,
    AccountType,
    AdminScope,
    ResourceGrantRecord,
    ResourceRecord,
    ResourceType,
    TemporaryCredentialRecord,
    UserRecord,
    has_admin_portal_access,
)
from .passwords import PasswordValidationError, hash_password, verify_password
from .policy import AccountPolicyError, ensure_can_manage_account
from .repositories import (
    AccountEnabledError,
    InvalidResourceGrantError,
    LastAdminError,
    OwnedResourcesError,
    SelfProtectionError,
    TemporaryCredentialExpiredError,
    TemporaryCredentialNotFoundError,
    UserNotFoundError,
    UsernameConflictError,
)
from .resources import resolve_admin_scope
from .runtime import AuthRuntime, get_auth_runtime
from .settings_repository import (
    ASR_PROVIDER_KEY,
    ASR_USER_CHOICES_KEY,
    BROWSER_ASR_PROVIDER,
    SERVER_ASR_PROVIDERS,
    InvalidSettingValueError,
    UnknownSettingError,
)

_SESSION_COOKIE_NAME = "openvman_session"
_INVALID_CREDENTIALS = "Invalid credentials"
_DUMMY_PASSWORD_HASH = "$2b$12$RHUg9KKg90SMUGjfwS3QxeboW/TeCDDpAZQBOcOOnOfYB64TsIfGO"
_TEMPORARY_PASSWORD_PATTERN = re.compile(
    r"\A(?:(?P<locator>[A-Za-z0-9]{12})[A-Za-z0-9]{8}"
    r"|(?P<legacy_locator>[A-Za-z0-9]{12}))\Z"
)

auth_router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
users_router = APIRouter(prefix="/api/v1/users", tags=["Accounts"])
# ASR 設定端點搬到 settings_routes.py。router 由那裡建立，這裡 re-export
# 讓 main.py 既有的 import 不用改。
from .settings_routes import settings_router  # noqa: E402

# 臨時帳號端點搬到 temporary_accounts_routes.py。這裡 re-export 讓 main.py 的 import 不用改。


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountDefaultsProfile(_StrictModel):
    project_id: str
    character_id: str
    voice_provider: str
    voice_id: str
    mascot_id: str = ""
    background_id: str = ""

    @classmethod
    def from_record(cls, record: AccountDefaultsRecord) -> AccountDefaultsProfile:
        return cls(
            project_id=record.project_id,
            character_id=record.character_id,
            voice_provider=record.voice_provider,
            voice_id=record.voice_id,
            mascot_id=record.mascot_id,
            background_id=record.background_id,
        )


class AccountResourceGrants(_StrictModel):
    projects: list[str] = Field(min_length=1)
    avatar_characters: list[str] = Field(min_length=1)
    custom_voices: list[str] = Field(min_length=1)
    avatar_mascots: list[str] = Field(default_factory=list)
    avatar_backgrounds: list[str] = Field(default_factory=list)
    # 不設 min_length：沒授權任何引擎就是「只能用預設值」，是合法狀態。
    asr_engines: list[str] = Field(default_factory=list)

    @classmethod
    def from_records(
        cls,
        records: tuple[ResourceGrantRecord, ...],
    ) -> AccountResourceGrants:
        values: dict[ResourceType, list[str]] = {
            ResourceType.PROJECT: [],
            ResourceType.AVATAR_CHARACTER: [],
            ResourceType.CUSTOM_VOICE: [],
            ResourceType.AVATAR_MASCOT: [],
            ResourceType.AVATAR_BACKGROUND: [],
            ResourceType.ASR_ENGINE: [],
        }
        for record in records:
            if record.resource_type in values:
                values[record.resource_type].append(record.resource_id)
        return cls(
            projects=values[ResourceType.PROJECT],
            avatar_characters=values[ResourceType.AVATAR_CHARACTER],
            custom_voices=values[ResourceType.CUSTOM_VOICE],
            avatar_mascots=values[ResourceType.AVATAR_MASCOT],
            avatar_backgrounds=values[ResourceType.AVATAR_BACKGROUND],
            asr_engines=values[ResourceType.ASR_ENGINE],
        )


def _resource_grants(
    grants: AccountResourceGrants,
) -> list[tuple[ResourceType, str]]:
    return [
        *((ResourceType.PROJECT, value) for value in grants.projects),
        *(
            (ResourceType.AVATAR_CHARACTER, value)
            for value in grants.avatar_characters
        ),
        *(
            (ResourceType.CUSTOM_VOICE, value)
            for value in grants.custom_voices
        ),
        *(
            (ResourceType.AVATAR_MASCOT, value)
            for value in grants.avatar_mascots
        ),
        *(
            (ResourceType.AVATAR_BACKGROUND, value)
            for value in grants.avatar_backgrounds
        ),
        *((ResourceType.ASR_ENGINE, value) for value in grants.asr_engines),
    ]


def _defaults_tuple(
    defaults: AccountDefaultsProfile,
) -> tuple[str, str, str, str, str, str]:
    return (
        defaults.project_id,
        defaults.character_id,
        defaults.voice_provider,
        defaults.voice_id,
        defaults.mascot_id,
        defaults.background_id,
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
    admin_portal_access: bool

    @classmethod
    def from_record(
        cls,
        user: UserRecord,
        *,
        runtime: AuthRuntime | None = None,
        credential: TemporaryCredentialRecord | None = None,
        now: datetime | None = None,
    ) -> AccountProfile:
        defaults = (
            runtime.account_access.get_defaults(user.id) if runtime else None
        )
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
            admin_portal_access=has_admin_portal_access(user),
            defaults=(
                AccountDefaultsProfile.from_record(defaults)
                if defaults is not None
                else None
            ),
        )


class AdminAccountProfile(AccountProfile):
    resource_counts: dict[str, int]
    grants: AccountResourceGrants | None

    @classmethod
    def from_record(
        cls,
        user: UserRecord,
        runtime: AuthRuntime,
    ) -> AdminAccountProfile:
        grant_records = runtime.account_access.list_grants(user.id)
        return cls(
            **AccountProfile.from_record(user, runtime=runtime).model_dump(),
            resource_counts=runtime.resources.count_private_by_owner(user.id),
            grants=(
                AccountResourceGrants.from_records(grant_records)
                if grant_records
                else None
            ),
        )


class LoginRequest(_StrictModel):
    username: str
    password: str


class TemporaryLoginRequest(_StrictModel):
    password: str


class ChangeOwnPasswordRequest(_StrictModel):
    current_password: str
    new_password: str


class LoginResponse(_StrictModel):
    account: AccountProfile
    token: str


class SetDisabledRequest(_StrictModel):
    disabled: bool


class LogoutResponse(_StrictModel):
    ok: bool



class UpdateAccountAccessRequest(_StrictModel):
    grants: AccountResourceGrants
    defaults: AccountDefaultsProfile
    admin_portal_access: bool = False



class CreateAccountRequest(_StrictModel):
    username: str
    password: str
    role: AccountRole = AccountRole.USER
    access: UpdateAccountAccessRequest | None = None


class ChangeAccountRoleRequest(_StrictModel):
    role: AccountRole
    access: UpdateAccountAccessRequest | None = None


class ResetAccountPasswordRequest(_StrictModel):
    password: str


class AccountAccessOption(_StrictModel):
    id: str
    label: str
    provider: str | None = None


class AccountAccessOptions(_StrictModel):
    projects: list[AccountAccessOption]
    avatar_characters: list[AccountAccessOption]
    custom_voices: list[AccountAccessOption]
    avatar_mascots: list[AccountAccessOption] = Field(default_factory=list)
    avatar_backgrounds: list[AccountAccessOption] = Field(default_factory=list)
    asr_engines: list[AccountAccessOption] = Field(default_factory=list)


class ResourceGrantProfile(_StrictModel):
    resource_type: ResourceType
    resource_id: str

    @classmethod
    def from_record(cls, record: ResourceGrantRecord) -> ResourceGrantProfile:
        return cls(
            resource_type=record.resource_type,
            resource_id=record.resource_id,
        )


class AdminScopeResources(_StrictModel):
    """Resource ids in an administrator's ceiling, by type.

    Unlike AccountResourceGrants every list may be empty: a ceiling that
    deliberately excludes a whole resource type is a valid thing for ROOT to
    express.
    """

    projects: list[str] = Field(default_factory=list)
    avatar_characters: list[str] = Field(default_factory=list)
    custom_voices: list[str] = Field(default_factory=list)
    avatar_mascots: list[str] = Field(default_factory=list)
    avatar_backgrounds: list[str] = Field(default_factory=list)
    # 不設 min_length：沒授權任何引擎就是「只能用預設值」，是合法狀態。
    asr_engines: list[str] = Field(default_factory=list)

    @classmethod
    def from_scope(cls, scope: AdminScope) -> AdminScopeResources:
        return cls(
            projects=sorted(scope.resource_ids(ResourceType.PROJECT)),
            avatar_characters=sorted(
                scope.resource_ids(ResourceType.AVATAR_CHARACTER),
            ),
            custom_voices=sorted(scope.resource_ids(ResourceType.CUSTOM_VOICE)),
            avatar_mascots=sorted(
                scope.resource_ids(ResourceType.AVATAR_MASCOT),
            ),
            avatar_backgrounds=sorted(
                scope.resource_ids(ResourceType.AVATAR_BACKGROUND),
            ),
            asr_engines=sorted(scope.resource_ids(ResourceType.ASR_ENGINE)),
        )

    def as_pairs(self) -> list[tuple[ResourceType, str]]:
        mapping = (
            (ResourceType.PROJECT, self.projects),
            (ResourceType.AVATAR_CHARACTER, self.avatar_characters),
            (ResourceType.CUSTOM_VOICE, self.custom_voices),
            (ResourceType.AVATAR_MASCOT, self.avatar_mascots),
            (ResourceType.AVATAR_BACKGROUND, self.avatar_backgrounds),
        )
        return [
            (resource_type, resource_id)
            for resource_type, resource_ids in mapping
            for resource_id in resource_ids
        ]


class AdminScopeProfile(_StrictModel):
    user_id: str
    scoped: bool
    resources: AdminScopeResources

    @classmethod
    def from_scope(cls, scope: AdminScope, user_id: str) -> AdminScopeProfile:
        return cls(
            user_id=user_id,
            scoped=scope.scoped,
            resources=AdminScopeResources.from_scope(scope),
        )


class UpdateAdminScopeRequest(_StrictModel):
    # scoped=False 清除上限，讓這個 admin 回到不受限狀態。
    scoped: bool
    resources: AdminScopeResources = Field(
        default_factory=AdminScopeResources,
    )


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



@users_router.get("", response_model=list[AdminAccountProfile])
def list_accounts(
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> list[AdminAccountProfile]:
    # 可見範圍必須跟 ensure_can_manage_account 一致，否則 admin 會看到一整份
    # 他動不了的名單，連 ROOT 有哪些私有資源都一併洩漏。
    if admin.user.role is AccountRole.ROOT:
        users = runtime.users.list(account_type=AccountType.FORMAL)
    else:
        users = runtime.users.list_visible_subtree(
            admin.user.id,
            account_type=AccountType.FORMAL,
        )
    return [AdminAccountProfile.from_record(user, runtime) for user in users]


def _resource_option(record: ResourceRecord) -> AccountAccessOption:
    try:
        metadata = json.loads(record.metadata_json)
    except (TypeError, ValueError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    label = metadata.get("label")
    provider = metadata.get("provider")
    return AccountAccessOption(
        id=record.resource_id,
        label=(
            label.strip()
            if isinstance(label, str) and label.strip()
            else record.resource_id
        ),
        provider=(
            provider.strip()
            if isinstance(provider, str) and provider.strip()
            else None
        ),
    )


def _scoped_options(
    runtime: AuthRuntime,
    scope: AdminScope,
    resource_type: ResourceType,
) -> list[AccountAccessOption]:
    """List assignable resources of one type, capped by the caller's scope."""
    records = runtime.resources.list_by_type(resource_type)
    if scope.scoped:
        allowed = scope.resource_ids(resource_type)
        records = [
            record for record in records if record.resource_id in allowed
        ]
    return [_resource_option(record) for record in records]


@users_router.get("/access-options", response_model=AccountAccessOptions)
def list_account_access_options(
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AccountAccessOptions:
    # 受限 admin 只能看到自己範圍內的選項——否則選單會列出他無權指派的
    # 資源，送出後才被後端擋掉。
    scope = resolve_admin_scope(admin.user, runtime.admin_scopes)
    return AccountAccessOptions(
        projects=_scoped_options(runtime, scope, ResourceType.PROJECT),
        avatar_characters=_scoped_options(
            runtime, scope, ResourceType.AVATAR_CHARACTER,
        ),
        custom_voices=_scoped_options(
            runtime, scope, ResourceType.CUSTOM_VOICE,
        ),
        avatar_mascots=_scoped_options(
            runtime, scope, ResourceType.AVATAR_MASCOT,
        ),
        avatar_backgrounds=_scoped_options(
            runtime, scope, ResourceType.AVATAR_BACKGROUND,
        ),
        asr_engines=_scoped_options(runtime, scope, ResourceType.ASR_ENGINE),
    )


@users_router.put("/{user_id}/access", response_model=AdminAccountProfile)
def update_account_access(
    user_id: str,
    body: UpdateAccountAccessRequest,
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AdminAccountProfile:
    try:
        runtime.account_access.replace(
            user_id=user_id,
            granted_by=admin.user.id,
            grants=_resource_grants(body.grants),
            defaults=_defaults_tuple(body.defaults),
            admin_portal_access=body.admin_portal_access,
        )
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Account not found",
        ) from exc
    except AccountPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InvalidResourceGrantError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    user = runtime.users.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return AdminAccountProfile.from_record(user, runtime)


@users_router.get(
    "/{user_id}/scope",
    response_model=AdminScopeProfile,
    summary="讀取管理員的資源上限",
)
def get_admin_scope(
    user_id: str,
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AdminScopeProfile:
    user = runtime.users.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if admin.user.role is not AccountRole.ROOT:
        try:
            ensure_can_manage_account(admin.user, user)
        except AccountPolicyError as exc:
            # 與 resolve_resource 一致：管不到的帳號等同不存在，不洩漏其存在。
            raise HTTPException(
                status_code=404,
                detail="Account not found",
            ) from exc
    return AdminScopeProfile.from_scope(
        runtime.admin_scopes.get(user_id),
        user_id,
    )


@users_router.put(
    "/{user_id}/scope",
    response_model=AdminScopeProfile,
    summary="設定管理員的資源上限",
)
def update_admin_scope(
    user_id: str,
    body: UpdateAdminScopeRequest,
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AdminScopeProfile:
    """Cap what an administrator may see and hand out.

    收斂是遞移的：受限 admin 再開帳號時，只能從自己這份上限裡分配。縮小
    範圍會一併撤銷他先前發出、如今已超出上限的授權。admin 也能設定自己
    建立的 admin，但只能給出自己上限的子集。
    """
    try:
        scope = runtime.admin_scopes.replace(
            admin_user_id=user_id,
            updated_by=admin.user.id,
            scoped=body.scoped,
            resources=body.resources.as_pairs(),
        )
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Account not found",
        ) from exc
    except AccountPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InvalidResourceGrantError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AdminScopeProfile.from_scope(scope, user_id)


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
        access = body.access
        user = runtime.users.create(
            username=body.username,
            password_hash=password_hash,
            role=body.role,
            created_by=admin.user.id,
            grants=_resource_grants(access.grants) if access is not None else None,
            defaults=_defaults_tuple(access.defaults) if access is not None else None,
            admin_portal_access=bool(access and access.admin_portal_access),
        )
    except AccountPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (InvalidResourceGrantError, PasswordValidationError, ValueError) as exc:
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
    except AccountPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (LastAdminError, SelfProtectionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AdminAccountProfile.from_record(user, runtime)


@users_router.post("/{user_id}/revoke", response_model=AdminAccountProfile)
def revoke_account_sessions(
    user_id: str,
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AdminAccountProfile:
    try:
        user = runtime.users.revoke_sessions(
            user_id,
            actor_id=admin.user.id,
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc
    except AccountPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
    except AccountPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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


@users_router.patch("/{user_id}/role", response_model=AdminAccountProfile)
def change_account_role(
    user_id: str,
    body: ChangeAccountRoleRequest,
    root: CurrentAccount = Depends(require_root),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AdminAccountProfile:
    access = body.access
    try:
        user = runtime.users.change_role(
            actor_id=root.user.id,
            user_id=user_id,
            role=body.role,
            grants=_resource_grants(access.grants) if access is not None else None,
            defaults=_defaults_tuple(access.defaults) if access is not None else None,
            admin_portal_access=bool(access and access.admin_portal_access),
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc
    except AccountPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InvalidResourceGrantError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AdminAccountProfile.from_record(user, runtime)


@users_router.post(
    "/{user_id}/password-reset",
    response_model=AdminAccountProfile,
)
def reset_account_password(
    user_id: str,
    body: ResetAccountPasswordRequest,
    root: CurrentAccount = Depends(require_root),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AdminAccountProfile:
    try:
        user = runtime.users.reset_password(
            actor_id=root.user.id,
            user_id=user_id,
            password_hash=hash_password(body.password),
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc
    except AccountPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PasswordValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AdminAccountProfile.from_record(user, runtime)


from .temporary_accounts_routes import (
    CreateTemporaryBatchRequest,
    SetAdminPortalAccessRequest,
    TemporaryAccountAudit,
    TemporaryBatchAudit,
    TemporaryBatchCreated,
    TemporaryCredentialCreated,
    temporary_accounts_router,
)

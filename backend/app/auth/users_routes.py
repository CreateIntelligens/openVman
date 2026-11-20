"""Administrator APIs for formal accounts and their resource grants."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import Field

from .account_access_options import AccountAccessOptions, scoped_options
from .account_presets import ACCOUNT_PRESETS, AccountPresetError, AccountPresetKey
from .account_schemas import (
    AccountDefaultsProfile,
    AccountResourceGrants,
    AdminAccountProfile,
    VendorAffiliationRequest,
    VendorName,
    _StrictModel,
    _defaults_tuple,
    _resource_grants,
)
from .admin_scope_routes import admin_scope_router
from .dependencies import CurrentAccount, require_admin, require_root
from .models import AccountRole, AccountType, ResourceType
from .passwords import PasswordValidationError, hash_password
from .policy import (
    AccountPolicyError,
    can_manage_vendor_accounts,
    is_vendor_account,
)
from .repository_errors import (
    AccountEnabledError,
    InvalidResourceGrantError,
    LastAdminError,
    OwnedResourcesError,
    SelfProtectionError,
    UserNotFoundError,
    UsernameConflictError,
)
from .resources import resolve_admin_scope
from .runtime import AuthRuntime, get_auth_runtime

users_router = APIRouter(prefix="/api/v1/users", tags=["Accounts"])
account_presets_router = APIRouter(prefix="/api/v1/admin", tags=["Accounts"])


class SetDisabledRequest(_StrictModel):
    disabled: bool


class UpdateAccountAccessRequest(_StrictModel):
    grants: AccountResourceGrants
    defaults: AccountDefaultsProfile
    admin_portal_access: bool = False
    # None 表示不變更：沿用舊版前端送來、不知道這個欄位的請求不會把它清掉。
    kiosk: bool | None = None
    ai_cleanup_access: bool | None = None
    web_search_access: bool | None = None


class UpdateAccountWebSearchRequest(_StrictModel):
    web_search_access: bool


class CreateAccountRequest(_StrictModel):
    username: str
    password: str
    role: AccountRole = AccountRole.USER
    access: UpdateAccountAccessRequest | UpdateAccountWebSearchRequest | None = None
    vendor_name: VendorName | None = None
    preset: AccountPresetKey | None = None
    project_ids: list[str] = Field(default_factory=list)


class AccountPresetProfile(_StrictModel):
    key: AccountPresetKey
    label: str
    description: str
    requires_vendor_name: bool
    requires_projects: bool


class SetAccountManagementAccessRequest(_StrictModel):
    enabled: bool


class ChangeAccountRoleRequest(_StrictModel):
    role: AccountRole
    access: UpdateAccountAccessRequest | None = None


class ResetAccountPasswordRequest(_StrictModel):
    password: str


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
            include_vendors=can_manage_vendor_accounts(admin.user),
        )
        if not can_manage_vendor_accounts(admin.user):
            users = [user for user in users if not is_vendor_account(user)]
    return [AdminAccountProfile.from_record(user, runtime) for user in users]


@users_router.get("/access-options", response_model=AccountAccessOptions)
def list_account_access_options(
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AccountAccessOptions:
    # 受限 admin 只能看到自己範圍內的選項——否則選單會列出他無權指派的
    # 資源，送出後才被後端擋掉。
    scope = resolve_admin_scope(admin.user, runtime.admin_scopes)
    return AccountAccessOptions(
        projects=scoped_options(
            runtime, scope, ResourceType.PROJECT, admin.user
        ),
        avatar_characters=scoped_options(
            runtime, scope, ResourceType.AVATAR_CHARACTER, admin.user
        ),
        custom_voices=scoped_options(
            runtime, scope, ResourceType.CUSTOM_VOICE, admin.user
        ),
        avatar_mascots=scoped_options(
            runtime, scope, ResourceType.AVATAR_MASCOT, admin.user
        ),
        avatar_backgrounds=scoped_options(
            runtime, scope, ResourceType.AVATAR_BACKGROUND, admin.user
        ),
        asr_engines=scoped_options(
            runtime, scope, ResourceType.ASR_ENGINE, admin.user
        ),
    )


@users_router.put("/{user_id}/access", response_model=AdminAccountProfile)
def update_account_access(
    user_id: str,
    body: UpdateAccountAccessRequest | UpdateAccountWebSearchRequest,
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AdminAccountProfile:
    access = body if isinstance(body, UpdateAccountAccessRequest) else None
    try:
        runtime.account_access.replace(
            user_id=user_id,
            granted_by=admin.user.id,
            grants=_resource_grants(access.grants) if access else None,
            defaults=_defaults_tuple(access.defaults) if access else None,
            admin_portal_access=bool(access and access.admin_portal_access),
            kiosk=access.kiosk if access else None,
            ai_cleanup_access=access.ai_cleanup_access if access else None,
            project_permissions=access.grants.project_permissions if access else None,
            web_search_access=body.web_search_access,
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


@account_presets_router.get("/account-presets")
def list_account_presets(
    admin: CurrentAccount = Depends(require_admin),
) -> list[AccountPresetProfile]:
    if not can_manage_vendor_accounts(admin.user):
        raise HTTPException(status_code=403, detail="需要帳號管理權限。")
    return [
        AccountPresetProfile(
            key=preset.key,
            label=preset.label,
            description=preset.description,
            requires_vendor_name=preset.requires_vendor_name,
            requires_projects=preset.requires_projects,
        )
        for preset in ACCOUNT_PRESETS.values()
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
        access = body.access if isinstance(body.access, UpdateAccountAccessRequest) else None
        user = runtime.users.create(
            username=body.username,
            password_hash=password_hash,
            role=body.role,
            created_by=admin.user.id,
            grants=_resource_grants(access.grants) if access is not None else None,
            defaults=_defaults_tuple(access.defaults) if access is not None else None,
            admin_portal_access=bool(access and access.admin_portal_access),
            kiosk=bool(access and access.kiosk),
            ai_cleanup_access=bool(access and access.ai_cleanup_access),
            vendor_name=body.vendor_name,
            project_permissions=access.grants.project_permissions if access else None,
            web_search_access=bool(body.access and body.access.web_search_access),
            preset=body.preset,
            project_ids=body.project_ids,
        )
    except AccountPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccountPresetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (InvalidResourceGrantError, PasswordValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UsernameConflictError as exc:
        raise HTTPException(status_code=409, detail="Username already exists") from exc
    return AdminAccountProfile.from_record(user, runtime)


@users_router.patch("/{user_id}/vendor", response_model=AdminAccountProfile)
def set_account_vendor(
    user_id: str,
    body: VendorAffiliationRequest,
    root: CurrentAccount = Depends(require_root),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AdminAccountProfile:
    try:
        user = runtime.users.set_vendor_affiliation(
            actor_id=root.user.id, user_id=user_id, vendor_name=body.vendor_name,
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc
    except AccountPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return AdminAccountProfile.from_record(user, runtime)


@users_router.patch("/{user_id}/account-management", response_model=AdminAccountProfile)
def set_account_management_access(
    user_id: str,
    body: SetAccountManagementAccessRequest,
    root: CurrentAccount = Depends(require_root),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AdminAccountProfile:
    try:
        user = runtime.users.set_account_management_access(
            actor_id=root.user.id, user_id=user_id, enabled=body.enabled,
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc
    except AccountPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
            kiosk=access.kiosk if access is not None else None,
            ai_cleanup_access=access.ai_cleanup_access if access is not None else None,
            project_permissions=access.grants.project_permissions if access else None,
            web_search_access=access.web_search_access if access else None,
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
    admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AdminAccountProfile:
    try:
        user = runtime.users.reset_password(
            actor_id=admin.user.id,
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


users_router.include_router(admin_scope_router)

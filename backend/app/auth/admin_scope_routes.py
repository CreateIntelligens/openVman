"""Administrator resource ceiling APIs (``/api/v1/users/{user_id}/scope``)."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import Field

from .dependencies import CurrentAccount, require_admin
from .models import AccountRole, AdminScope, ResourceType
from .policy import AccountPolicyError, ensure_can_manage_account
from .repositories import InvalidResourceGrantError, UserNotFoundError
from .routes import _StrictModel, users_router
from .runtime import AuthRuntime, get_auth_runtime


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

"""Typed persistence models for accounts and owned resources."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum


class AccountRole(StrEnum):
    ROOT = "root"
    ADMIN = "admin"
    USER = "user"


_ACCOUNT_ROLE_RANK = {
    AccountRole.USER: 0,
    AccountRole.ADMIN: 1,
    AccountRole.ROOT: 2,
}

# 唯一 ROOT 帳號的登入名稱。部署可用 AUTH_ROOT_USERNAME 覆寫；預設值是
# 既有部署的名稱，所以不設環境變數時行為不變。
ROOT_USERNAME = os.getenv("AUTH_ROOT_USERNAME", "ai360").strip().casefold() or "ai360"


def role_at_least(role: AccountRole, minimum: AccountRole) -> bool:
    """Return whether a role satisfies a centralized hierarchy threshold."""
    return _ACCOUNT_ROLE_RANK[role] >= _ACCOUNT_ROLE_RANK[minimum]


def is_at_least_admin(role: AccountRole) -> bool:
    return role_at_least(role, AccountRole.ADMIN)


def has_admin_portal_access(user: UserRecord) -> bool:
    """Return the effective Admin portal capability for an account."""
    return is_at_least_admin(user.role) or user.admin_portal_access


# 「admin 以上」的角色值，供 SQL 的 IN 子句使用。從階層推導而非寫死字面
# 列表，新增角色時不會漏掉這裡。
ADMIN_OR_ABOVE_VALUES = tuple(
    role.value for role in AccountRole if is_at_least_admin(role)
)


class AccountType(StrEnum):
    FORMAL = "formal"
    TEMPORARY = "temporary"


class ResourceVisibility(StrEnum):
    PRIVATE = "private"
    SYSTEM_PUBLIC = "system_public"


class ResourceType(StrEnum):
    PROJECT = "project"
    AVATAR_CHARACTER = "avatar_character"
    AVATAR_BACKGROUND = "avatar_background"
    AVATAR_MASCOT = "avatar_mascot"
    CUSTOM_VOICE = "custom_voice"


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: str
    username: str
    username_normalized: str
    password_hash: str
    role: AccountRole
    account_type: AccountType
    disabled: bool
    token_version: int
    created_at: str
    updated_at: str
    created_by: str | None
    admin_portal_access: bool = False


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    resource_type: ResourceType
    resource_id: str
    owner_user_id: str | None
    visibility: ResourceVisibility
    created_at: str
    metadata_json: str


@dataclass(frozen=True, slots=True)
class TemporaryCredentialRecord:
    user_id: str
    batch_id: str
    code_locator: str
    first_used_at: str | None
    expires_at: str | None
    duration_seconds: int


@dataclass(frozen=True, slots=True)
class ResourceGrantRecord:
    grantee_user_id: str
    resource_type: ResourceType
    resource_id: str
    granted_by: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class AccountDefaultsRecord:
    user_id: str
    project_id: str
    character_id: str
    voice_provider: str
    voice_id: str
    mascot_id: str = ""
    background_id: str = ""


@dataclass(frozen=True, slots=True)
class TemporaryBatchRecord:
    id: str
    created_by: str | None
    created_at: str
    revoked_at: str | None


@dataclass(frozen=True, slots=True)
class AuthAuditEventRecord:
    id: str
    action: str
    actor_user_id: str | None
    target_user_id: str | None
    created_at: str
    metadata_json: str

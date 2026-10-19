"""Typed persistence models for accounts and owned resources."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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
    # Embed 主體不是資料庫裡的帳號，只在請求期間由 embed key 合成，
    # 所以 users 表的 CHECK 約束刻意不含這個值。
    EMBED = "embed"


class ResourceVisibility(StrEnum):
    PRIVATE = "private"
    SYSTEM_PUBLIC = "system_public"
    PROJECT = "project"


class ResourceType(StrEnum):
    PROJECT = "project"
    AVATAR_CHARACTER = "avatar_character"
    AVATAR_BACKGROUND = "avatar_background"
    AVATAR_MASCOT = "avatar_mascot"
    CUSTOM_VOICE = "custom_voice"
    ASR_ENGINE = "asr_engine"


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
    # 展示機台：前台登入後一律進訪客模式（藏設定與登出），現場人員輸入本帳號
    # 密碼才能解鎖。只影響前台行為，不是權限，所以切換時不撤銷既有 session。
    kiosk: bool = False
    # None 表示升級後還沒登入過；只在登入成功時寫，不代表 API key 的使用。
    last_login_at: str | None = None


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    resource_type: ResourceType
    resource_id: str
    owner_user_id: str | None
    visibility: ResourceVisibility
    created_at: str
    metadata_json: str
    owner_project_id: str | None = None


@dataclass(frozen=True, slots=True)
class TemporaryCredentialRecord:
    user_id: str
    batch_id: str
    code_locator: str
    first_used_at: str | None
    expires_at: str | None
    duration_seconds: int
    password_ciphertext: str | None = field(default=None, repr=False)


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
class ProjectPolicyRecord:
    """Per-project voice and resource limits layered on top of account grants.

    空清單代表「專案不另外限制」，所以沒有設定的專案行為與以前完全一樣；
    請求實際能用的是帳號授權與這份清單的交集。
    """

    project_id: str
    allowed_asr_engines: tuple[str, ...] = ()
    default_asr_engine: str | None = None
    taiwanese_asr_engine: str | None = None
    allowed_tts_voices: tuple[str, ...] = ()
    default_tts_voice: str | None = None
    allowed_characters: tuple[str, ...] = ()
    default_character_id: str | None = None
    allowed_backgrounds: tuple[str, ...] = ()
    default_background_id: str | None = None
    allowed_mascots: tuple[str, ...] = ()
    default_mascot_id: str | None = None
    #: TTS 引擎順位：請求沒指定引擎與聲音時照這個順序試，台語分流也照它挑
    #: CosyVoice／VoxCPM 誰先；空的就用部署的鏈。
    tts_engine_order: tuple[str, ...] = ()
    #: 批次 ASR 備援順位：呼叫端指定的引擎之後照這個順序試；空的就用部署的鏈。
    asr_engine_order: tuple[str, ...] = ()
    updated_by: str | None = None
    updated_at: str | None = None

    @property
    def restricts_asr(self) -> bool:
        return bool(self.allowed_asr_engines)

    @property
    def restricts_tts(self) -> bool:
        return bool(self.allowed_tts_voices)

    @property
    def restricts_characters(self) -> bool:
        return bool(self.allowed_characters)

    @property
    def restricts_backgrounds(self) -> bool:
        return bool(self.allowed_backgrounds)

    @property
    def restricts_mascots(self) -> bool:
        return bool(self.allowed_mascots)

    def allows_asr(self, engine: str) -> bool:
        return not self.allowed_asr_engines or engine in self.allowed_asr_engines

    def allows_voice(self, voice_id: str) -> bool:
        return not self.allowed_tts_voices or voice_id in self.allowed_tts_voices

    def allows_character(self, character_id: str) -> bool:
        return not self.allowed_characters or character_id in self.allowed_characters

    def allows_background(self, background_id: str) -> bool:
        return not self.allowed_backgrounds or background_id in self.allowed_backgrounds

    def allows_mascot(self, mascot_id: str) -> bool:
        return not self.allowed_mascots or mascot_id in self.allowed_mascots

    def narrow_asr(self, engines: set[str]) -> set[str]:
        if not self.allowed_asr_engines:
            return set(engines)
        return {engine for engine in engines if engine in self.allowed_asr_engines}


@dataclass(frozen=True, slots=True)
class ProjectResourceAssignmentRecord:
    project_id: str
    resource_type: ResourceType
    resource_id: str
    assigned_by: str | None
    assigned_at: str


@dataclass(frozen=True, slots=True)
class TemporaryBatchRecord:
    id: str
    created_by: str | None
    created_at: str
    revoked_at: str | None


@dataclass(frozen=True, slots=True)
class EmbedKeyRecord:
    key_id: str
    label: str
    project_id: str
    allowed_origins: tuple[str, ...]
    default_character_id: str
    allowed_character_ids: tuple[str, ...]
    default_persona_id: str
    default_tts_provider: str
    default_tts_voice: str
    rate_limit_per_minute: int
    daily_request_quota: int
    disabled: bool
    created_by: str | None
    created_at: str
    updated_at: str
    last_used_at: str | None

    def allows_origin(self, origin: str) -> bool:
        """Match the exact `scheme://host[:port]` string, case-insensitively."""
        candidate = origin.strip().casefold()
        if not candidate:
            return False
        return any(allowed.casefold() == candidate for allowed in self.allowed_origins)

    def allows_character(self, character_id: str) -> bool:
        candidate = character_id.strip()
        if not candidate:
            return False
        return candidate == self.default_character_id or (
            candidate in self.allowed_character_ids
        )


@dataclass(frozen=True, slots=True)
class AdminScopeRecord:
    """One resource ROOT has placed in an administrator's assignable pool."""

    admin_user_id: str
    resource_type: ResourceType
    resource_id: str
    granted_by: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class AdminScope:
    """An administrator's effective resource ceiling.

    ``scoped`` is the distinction that matters: an unscoped administrator keeps
    the historical unrestricted access, while a scoped one may only see and
    hand out what ``resources`` lists — including the case where ROOT has
    deliberately left a resource type empty.
    """

    admin_user_id: str
    scoped: bool
    resources: frozenset[tuple[ResourceType, str]]

    def allows(self, resource_type: ResourceType, resource_id: str) -> bool:
        if not self.scoped:
            return True
        return (resource_type, resource_id) in self.resources

    def resource_ids(self, resource_type: ResourceType) -> frozenset[str]:
        return frozenset(
            item[1] for item in self.resources if item[0] is resource_type
        )


UNSCOPED_ADMIN = AdminScope(
    admin_user_id="",
    scoped=False,
    resources=frozenset(),
)


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    """Public key metadata; the credential digest never leaves its repository."""

    key_id: str
    user_id: str
    label: str
    created_at: str
    expires_at: str | None
    revoked_at: str | None
    last_used_at: str | None
    request_count: int
    token_prefix: str


@dataclass(frozen=True, slots=True)
class AuthAuditEventRecord:
    id: str
    action: str
    actor_user_id: str | None
    target_user_id: str | None
    created_at: str
    metadata_json: str

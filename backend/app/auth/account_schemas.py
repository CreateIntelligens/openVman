"""Shared account profiles, resource grants, and vendor affiliation schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_serializer,
)

from .account_presets import AccountPresetKey, derive_account_preset
from .models import (
    AccountDefaultsRecord,
    AccountRole,
    AccountType,
    ProjectWritePermissions,
    ResourceGrantRecord,
    ResourceType,
    TemporaryCredentialRecord,
    UserRecord,
    has_admin_portal_access,
    has_ai_cleanup_access,
    has_web_search_access,
)
from .policy import is_vendor_account
from .runtime import AuthRuntime


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


VendorName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]


class VendorAffiliationRequest(_StrictModel):
    vendor_name: VendorName | None


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


class AccountResourceGrantsView(_StrictModel):
    """Grants as stored, for reading.

    讀取不檢查「專案、人物、聲音至少各一」：資料庫裡可能有只被授權辨識引擎的帳號
    （2026-10-14 正式機有 4 個），用寫入規則驗證讀出來的資料會讓整個帳號列表 500、
    後台帳號頁打不開。
    """

    projects: list[str] = Field(default_factory=list)
    avatar_characters: list[str] = Field(default_factory=list)
    custom_voices: list[str] = Field(default_factory=list)
    avatar_mascots: list[str] = Field(default_factory=list)
    avatar_backgrounds: list[str] = Field(default_factory=list)
    asr_engines: list[str] = Field(default_factory=list)
    project_permissions: dict[str, ProjectWritePermissions] | None = None

    @classmethod
    def from_records(
        cls,
        records: tuple[ResourceGrantRecord, ...],
        *,
        vendor_account: bool = False,
    ) -> "AccountResourceGrantsView":
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
            project_permissions={
                record.resource_id: ProjectWritePermissions(
                    record.edit_knowledge, record.edit_settings and not vendor_account,
                )
                for record in records if record.resource_type is ResourceType.PROJECT
            },
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


class AccountResourceGrants(AccountResourceGrantsView):
    """Grants as written: an account must get at least one project, character and voice."""

    projects: list[str] = Field(min_length=1)
    avatar_characters: list[str] = Field(min_length=1)
    custom_voices: list[str] = Field(min_length=1)
    avatar_mascots: list[str] = Field(default_factory=list)
    avatar_backgrounds: list[str] = Field(default_factory=list)
    # 不設 min_length：沒授權任何引擎就是「只能用預設值」，是合法狀態。
    asr_engines: list[str] = Field(default_factory=list)


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
    # 前台據此決定登入後是否強制進訪客模式。
    kiosk: bool
    # 生效值：管理員以上一律為真。後台據此決定要不要顯示「AI 整理排版」。
    ai_cleanup_access: bool = False
    web_search_access: bool = False
    vendor_name: str | None = None
    account_management_access: bool = False

    @model_serializer(mode="wrap")
    def _serialize_profile(self, serialize):
        result = serialize(self)
        if self.role is AccountRole.USER:
            result.pop("account_management_access", None)
            if self.vendor_name and not isinstance(self, AdminAccountProfile):
                result.pop("created_by", None)
                result.pop("ai_cleanup_access", None)
                result.pop("web_search_access", None)
        return result

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
            kiosk=user.kiosk,
            ai_cleanup_access=has_ai_cleanup_access(user),
            web_search_access=has_web_search_access(user),
            vendor_name=user.vendor_name,
            account_management_access=user.account_management_access,
            defaults=(
                AccountDefaultsProfile.from_record(defaults)
                if defaults is not None
                else None
            ),
        )


class AdminAccountProfile(AccountProfile):
    resource_counts: dict[str, int]
    grants: AccountResourceGrantsView | None
    preset: AccountPresetKey | None = None
    preset_label: str | None = None
    # 後台清理帳號用：None 表示升級後還沒登入過／從沒用過 API key。
    last_login_at: str | None = None
    api_key_last_used_at: str | None = None

    @classmethod
    def from_record(
        cls,
        user: UserRecord,
        runtime: AuthRuntime,
    ) -> AdminAccountProfile:
        grant_records = runtime.account_access.list_grants(user.id)
        profile = AccountProfile.from_record(user, runtime=runtime).model_dump()
        profile["created_by"] = user.created_by
        # 對外的廠商 profile 不帶這個欄位；管理畫面要看到實際值，否則存檔會把權限關掉。
        profile["ai_cleanup_access"] = has_ai_cleanup_access(user)
        profile["web_search_access"] = has_web_search_access(user)
        preset = derive_account_preset(user, grant_records)
        return cls(
            **profile,
            preset=preset.key if preset else None,
            preset_label=preset.label if preset else None,
            resource_counts=runtime.resources.count_private_by_owner(user.id),
            grants=(
                AccountResourceGrantsView.from_records(
                    grant_records, vendor_account=is_vendor_account(user),
                )
                if grant_records
                else None
            ),
            last_login_at=user.last_login_at,
            api_key_last_used_at=runtime.api_keys.last_used_at_for_user(user.id),
        )


class ResourceGrantProfile(_StrictModel):
    resource_type: ResourceType
    resource_id: str

    @classmethod
    def from_record(cls, record: ResourceGrantRecord) -> ResourceGrantProfile:
        return cls(
            resource_type=record.resource_type,
            resource_id=record.resource_id,
        )

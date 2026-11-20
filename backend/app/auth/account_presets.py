"""Creation rules and derived labels for formal account presets."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from .models import (
    AccountRole,
    AccountType,
    ProjectWritePermissions,
    ResourceGrantRecord,
    ResourceType,
    UserRecord,
)


class AccountPresetKey(StrEnum):
    RD = "rd"
    BD = "bd"
    VENDOR_EDITOR = "vendor_editor"


class AccountPresetError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AccountPreset:
    key: AccountPresetKey
    label: str
    description: str
    role: AccountRole
    requires_vendor_name: bool = False
    project_permissions: ProjectWritePermissions | None = None
    allow_empty_projects: bool = True
    admin_portal_access: bool = True
    account_management_access: bool = False
    web_search_access: bool = False
    ai_cleanup_access: bool = False

    @property
    def requires_projects(self) -> bool:
        return self.project_permissions is not None

    def selected_projects(
        self, project_ids: Iterable[str], vendor_name: str | None,
    ) -> tuple[str, ...]:
        if self.requires_vendor_name and not vendor_name:
            raise AccountPresetError("廠商編輯必須填寫所屬廠商。")
        if not self.requires_vendor_name and vendor_name:
            raise AccountPresetError(f"{self.label}帳號不可填寫所屬廠商。")
        projects = tuple(sorted({value.strip() for value in project_ids if value.strip()}))
        if not self.requires_projects and projects:
            raise AccountPresetError(f"{self.label}帳號不需指定知識庫。")
        if not self.allow_empty_projects and not projects:
            raise AccountPresetError("請至少選擇一個知識庫。")
        return projects

    def matches(
        self, user: UserRecord, projects: tuple[ResourceGrantRecord, ...],
    ) -> bool:
        return (
            user.role is self.role
            and user.admin_portal_access == self.admin_portal_access
            and user.account_management_access == self.account_management_access
            and bool(user.vendor_name) == self.requires_vendor_name
            and user.web_search_access == self.web_search_access
            and user.ai_cleanup_access == self.ai_cleanup_access
            and (
                not projects if self.project_permissions is None else (
                    (bool(projects) or self.allow_empty_projects)
                    and all(
                        grant.edit_knowledge == self.project_permissions.edit_knowledge
                        and grant.edit_settings == self.project_permissions.edit_settings
                        for grant in projects
                    )
                )
            )
        )


ACCOUNT_PRESETS = {
    AccountPresetKey.RD: AccountPreset(
        key=AccountPresetKey.RD,
        label="創智研發",
        description=(
            "管理員，可進入後台、管理帳號、使用網路搜尋與 AI 整理排版。"
            "知識庫依管理員權限開放。"
        ),
        role=AccountRole.ADMIN,
        account_management_access=True,
        web_search_access=True,
    ),
    AccountPresetKey.BD: AccountPreset(
        key=AccountPresetKey.BD,
        label="BD",
        description=(
            "一般帳號，可進入後台、編輯選取的知識庫和角色，並使用網路搜尋。"
            "帳號管理與 AI 整理排版關閉。"
        ),
        role=AccountRole.USER,
        project_permissions=ProjectWritePermissions(edit_knowledge=True),
        web_search_access=True,
    ),
    AccountPresetKey.VENDOR_EDITOR: AccountPreset(
        key=AccountPresetKey.VENDOR_EDITOR,
        label="廠商編輯",
        description=(
            "一般帳號，可進入廠商後台，編輯指定的同廠商知識庫和角色。"
            "帳號管理、網路搜尋與 AI 整理排版關閉。"
        ),
        role=AccountRole.USER,
        requires_vendor_name=True,
        project_permissions=ProjectWritePermissions(edit_knowledge=True),
        allow_empty_projects=False,
    ),
}


def derive_account_preset(
    user: UserRecord, grants: Iterable[ResourceGrantRecord],
) -> AccountPreset | None:
    if user.account_type is not AccountType.FORMAL or user.kiosk:
        return None
    projects = tuple(
        grant for grant in grants if grant.resource_type is ResourceType.PROJECT
    )
    return next(
        (preset for preset in ACCOUNT_PRESETS.values() if preset.matches(user, projects)),
        None,
    )

"""Single source of truth for effective project resources and defaults."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from .models import (
    AccountRole,
    ResourceType,
    ResourceVisibility,
    UserRecord,
)
from .resources import list_accessible_resources
from .runtime import AuthRuntime


@dataclass(frozen=True, slots=True)
class ProjectResourceEntry:
    resource_id: str
    source: Literal["grant", "project", "assigned"]
    label: str = ""
    in_project_scope: bool = True


def _extract_label(metadata_json: str, default: str) -> str:
    try:
        data = json.loads(metadata_json)
        if isinstance(data, dict):
            for key in ("label", "name"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
    except (TypeError, ValueError):
        pass
    return default


def effective_project_resources(
    runtime: AuthRuntime,
    account: UserRecord | None,
    project_id: str,
    resource_type: ResourceType,
) -> list[ProjectResourceEntry]:
    """Compute effective resources for an account (or embed key) in a project.

    grant    = 全域資源 ∩ 帳號可用（沿用 list_accessible_resources，ROOT／不受限 admin＝全部）；
               ROOT 另含其他專案的專屬資源與孤兒，標成範圍外
               ∩ 專案清單（清單為空＝不限制）
    project  = resources.owner_project_id == project_id 的資源（不看帳號授權、不看專案清單）
    assigned = project_resource_assignments 裡這個專案的項目（不看帳號授權、不看專案清單）
    結果     = grant ∪ project ∪ assigned，同一 ID 只出現一次，source 取 assigned > project > grant
    """
    policy = runtime.project_policies.get(project_id)

    # 1. grant
    is_root = account is not None and account.role is AccountRole.ROOT
    grant_ids: set[str] = set()
    in_scope_grant_ids: set[str] = set()
    if account is None:
        # Embed key: 專案有清單時以清單代替帳號授權
        if policy is not None:
            if resource_type is ResourceType.CUSTOM_VOICE and policy.restricts_tts:
                grant_ids = set(policy.allowed_tts_voices)
            elif resource_type is ResourceType.ASR_ENGINE and policy.restricts_asr:
                grant_ids = set(policy.allowed_asr_engines)
            elif (
                resource_type is ResourceType.AVATAR_CHARACTER
                and policy.restricts_characters
            ):
                grant_ids = set(policy.allowed_characters)
            elif (
                resource_type is ResourceType.AVATAR_BACKGROUND
                and policy.restricts_backgrounds
            ):
                grant_ids = set(policy.allowed_backgrounds)
            elif (
                resource_type is ResourceType.AVATAR_MASCOT
                and policy.restricts_mascots
            ):
                grant_ids = set(policy.allowed_mascots)
        in_scope_grant_ids = grant_ids
    else:
        accessible_records = list_accessible_resources(
            runtime.resources,
            account,
            resource_type,
            admin_scopes=runtime.admin_scopes,
        )
        accessible_system_public = {
            r.resource_id
            for r in accessible_records
            if r.visibility is ResourceVisibility.SYSTEM_PUBLIC
        }
        if policy is None:
            grant_ids = accessible_system_public
            in_scope_grant_ids = accessible_system_public
        else:
            if resource_type is ResourceType.CUSTOM_VOICE and policy.restricts_tts:
                in_scope_grant_ids = accessible_system_public & set(
                    policy.allowed_tts_voices
                )
            elif resource_type is ResourceType.ASR_ENGINE and policy.restricts_asr:
                in_scope_grant_ids = accessible_system_public & set(
                    policy.allowed_asr_engines
                )
            elif (
                resource_type is ResourceType.AVATAR_CHARACTER
                and policy.restricts_characters
            ):
                in_scope_grant_ids = accessible_system_public & set(
                    policy.allowed_characters
                )
            elif (
                resource_type is ResourceType.AVATAR_BACKGROUND
                and policy.restricts_backgrounds
            ):
                in_scope_grant_ids = accessible_system_public & set(
                    policy.allowed_backgrounds
                )
            elif (
                resource_type is ResourceType.AVATAR_MASCOT
                and policy.restricts_mascots
            ):
                in_scope_grant_ids = accessible_system_public & set(
                    policy.allowed_mascots
                )
            else:
                in_scope_grant_ids = accessible_system_public

            if is_root:
                grant_ids = accessible_system_public
            else:
                grant_ids = in_scope_grant_ids

        if is_root:
            # ROOT 在任何專案都能選所有資源，別的專案的專屬資源與孤兒標成範圍外。
            # 2026-10-16 人物全改成專案專屬後，只看全域資源會讓 ROOT 在 AWS-dev
            # 看不到 default 的 009 等人物。
            grant_ids = grant_ids | {
                r.resource_id
                for r in accessible_records
                if r.visibility is ResourceVisibility.PROJECT
            }

    # 2. project
    project_records = runtime.resources.list_by_owner_project(
        project_id, resource_type=resource_type
    )
    project_ids = {
        r.resource_id
        for r in project_records
        if r.visibility is ResourceVisibility.PROJECT
    }

    # 3. assigned
    assigned_records = (
        runtime.project_resource_assignments.list_for_project(
            project_id, resource_type=resource_type
        )
    )
    assigned_ids = {r.resource_id for r in assigned_records}

    # Combine: assigned > project > grant
    all_ids = sorted(grant_ids | project_ids | assigned_ids)
    entries: list[ProjectResourceEntry] = []
    for rid in all_ids:
        if rid in assigned_ids:
            source: Literal["grant", "project", "assigned"] = "assigned"
        elif rid in project_ids:
            source = "project"
        else:
            source = "grant"

        record = runtime.resources.get(resource_type, rid)
        label = _extract_label(record.metadata_json if record else "{}", rid)
        in_project_scope = (
            rid in assigned_ids
            or rid in project_ids
            or rid in in_scope_grant_ids
        )
        entries.append(
            ProjectResourceEntry(
                resource_id=rid,
                source=source,
                label=label,
                in_project_scope=in_project_scope,
            )
        )
    return entries


def effective_project_default(
    runtime: AuthRuntime,
    account: UserRecord | None,
    project_id: str,
    resource_type: ResourceType,
    available_entries: list[ProjectResourceEntry] | None = None,
) -> str | None:
    """順序為專案預設 → 帳號預設（account_defaults）→ 結果清單第一個；每一步都必須在結果清單內才採用。"""
    if available_entries is None:
        available_entries = effective_project_resources(
            runtime, account, project_id, resource_type
        )
    available_ids = {e.resource_id for e in available_entries}
    if not available_ids:
        return None

    policy = runtime.project_policies.get(project_id)
    # 1. 專案預設
    project_default: str | None = None
    if policy is not None:
        if resource_type is ResourceType.AVATAR_CHARACTER:
            project_default = policy.default_character_id
        elif resource_type is ResourceType.AVATAR_BACKGROUND:
            project_default = policy.default_background_id
        elif resource_type is ResourceType.AVATAR_MASCOT:
            project_default = policy.default_mascot_id
        elif resource_type is ResourceType.CUSTOM_VOICE:
            project_default = policy.default_tts_voice
        elif resource_type is ResourceType.ASR_ENGINE:
            project_default = policy.default_asr_engine

    if project_default and project_default in available_ids:
        return project_default

    # 2. 帳號預設
    if account is not None:
        defaults = runtime.account_access.get_defaults(account.id)
        if defaults is not None:
            acct_val: str | None = None
            if resource_type is ResourceType.AVATAR_CHARACTER:
                acct_val = defaults.character_id
            elif resource_type is ResourceType.AVATAR_BACKGROUND:
                acct_val = defaults.background_id
            elif resource_type is ResourceType.AVATAR_MASCOT:
                acct_val = defaults.mascot_id
            elif resource_type is ResourceType.CUSTOM_VOICE:
                acct_val = defaults.voice_id
            elif resource_type is ResourceType.ASR_ENGINE:
                acct_val = runtime.account_access.get_asr_provider(account.id)

            if acct_val and acct_val in available_ids:
                return acct_val

    # 3. 可用清單第一個（若有專案範圍內的項目優先採用，避免 ROOT 預設走到清單外項目）
    in_scope_entries = [e for e in available_entries if e.in_project_scope]
    return (in_scope_entries or available_entries)[0].resource_id



def unscoped_resource_sources(
    runtime: AuthRuntime,
    account: UserRecord,
    resource_type: ResourceType,
) -> dict[str, tuple[str, str | None]]:
    """Resources an account sees in a list without a project: id → (source, owner project).

    一般帳號只看得到全域資源。ROOT 的資源管理頁要看到全部，包含各專案的專屬資源
    （source="project"，附擁有的專案）與擁有專案已刪除的孤兒資源（source="orphan"）。
    """
    is_root = account.role is AccountRole.ROOT
    sources: dict[str, tuple[str, str | None]] = {}
    for resource in list_accessible_resources(runtime.resources, account, resource_type):
        if resource.visibility is not ResourceVisibility.PROJECT:
            sources[resource.resource_id] = ("grant", None)
        elif is_root:
            owner = resource.owner_project_id
            sources[resource.resource_id] = ("project" if owner else "orphan", owner)
    return sources

"""Resolve ASR preferences against current grants for UI and workers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import AccountRole, ResourceType, UserRecord

if TYPE_CHECKING:
    from .runtime import AuthRuntime


def asr_user_choices(runtime: AuthRuntime, account: UserRecord) -> list[str]:
    if account.role is AccountRole.ROOT:
        return sorted(
            record.resource_id
            for record in runtime.resources.list_by_type(ResourceType.ASR_ENGINE)
        )
    return sorted(
        grant.resource_id
        for grant in runtime.account_access.list_grants(account.id)
        if grant.resource_type is ResourceType.ASR_ENGINE
    )


def permitted_asr_preference(
    runtime: AuthRuntime, account: UserRecord, stored: str,
) -> str:
    # Grants may have changed after the preference was saved or a job queued.
    return stored if stored in asr_user_choices(runtime, account) else ""

"""Right-corner mascot catalog API.

小助理只剩內建的 Live2D Haru，這裡只負責依帳號與專案權限決定看不看得到它；
沒有上傳、改名、刪除或縮圖端點。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import CurrentAccount, get_current_account
from app.auth.models import ResourceType
from app.auth.project_resources import (
    effective_project_resources,
    unscoped_resource_sources,
)
from app.auth.resources import (
    ResourceAccess,
    ResourceNotFoundError,
    resolve_resource,
)
from app.auth.runtime import AuthRuntime, get_auth_runtime
from app.avatar.mascot_store import builtin_mascots

router = APIRouter()


@router.get("/api/v1/avatar/mascots", summary="列出右下角小助理")
async def list_mascots(
    project_id: str | None = None,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, list[dict[str, Any]]]:
    if project_id:
        try:
            resolve_resource(
                runtime.resources,
                current.user,
                ResourceType.PROJECT,
                project_id,
                access=ResourceAccess.READ,
            )
        except ResourceNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"專案不存在或無權限存取：{project_id}",
            )
        entries = {
            entry.resource_id: entry
            for entry in effective_project_resources(
                runtime, current.user, project_id, ResourceType.AVATAR_MASCOT
            )
        }
        return {
            "mascots": [
                {
                    **mascot,
                    "source": entries[mascot["mascot_id"]].source,
                    "in_project_scope": entries[mascot["mascot_id"]].in_project_scope,
                }
                for mascot in builtin_mascots()
                if mascot["mascot_id"] in entries
            ]
        }

    sources = unscoped_resource_sources(
        runtime, current.user, ResourceType.AVATAR_MASCOT,
    )
    return {
        "mascots": [
            {
                **mascot,
                "source": sources[mascot["mascot_id"]][0],
                "owner_project_id": sources[mascot["mascot_id"]][1],
            }
            for mascot in builtin_mascots()
            if mascot["mascot_id"] in sources
        ]
    }

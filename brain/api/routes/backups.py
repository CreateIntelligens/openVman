"""Session backup endpoints (VH-389).

只接受 internal token；對外由 Backend 的 root 專用路由轉發，一般帳號走
catch-all 代理會被擋在 Backend（backups 列在 _BACKEND_OWNED_PREFIXES）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from memory.session_backup import (
    BackupInProgressError,
    backup_running,
    list_backups,
    run_backup,
)
from safety.internal_auth import require_internal_token

router = APIRouter(
    prefix="/brain/backups",
    tags=["Backups"],
    dependencies=[Depends(require_internal_token)],
)


class RunBackupRequest(BaseModel):
    dry_run: bool = False


@router.get("/sessions", summary="列出對話備份")
def get_session_backups() -> dict[str, Any]:
    return {"backups": list_backups(), "running": backup_running()}


@router.post("/sessions", summary="立即備份對話（可先 dry-run）")
async def post_session_backup(body: RunBackupRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(run_backup, dry_run=body.dry_run)
    except BackupInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

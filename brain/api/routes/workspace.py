from __future__ import annotations

from fastapi import APIRouter, Depends

from safety.internal_auth import require_internal_token

# This module is intentionally empty for now. The active API surface has no
# /brain/workspace/* endpoints, but the change spec reserves the module slot.
router = APIRouter(
    prefix="/brain/workspace",
    tags=["Knowledge"],
    dependencies=[Depends(require_internal_token)],
)

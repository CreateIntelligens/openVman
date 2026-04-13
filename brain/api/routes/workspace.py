from __future__ import annotations

from fastapi import APIRouter

# This module is intentionally empty for now. The active API surface has no
# /brain/workspace/* endpoints, but the change spec reserves the module slot.
router = APIRouter(prefix="/brain/workspace", tags=["Knowledge"])


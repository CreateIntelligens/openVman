from __future__ import annotations

from fastapi import APIRouter

from health_payload import build_health_payload
from knowledge.workspace import parse_identity
from safety.observability import get_metrics_store

router = APIRouter(prefix="/brain", tags=["System"])


@router.get("/health", summary="大腦層健康檢查")
async def health(project_id: str = "default"):
    return build_health_payload(project_id)


@router.get("/metrics", summary="大腦層監控指標")
async def metrics():
    return get_metrics_store().snapshot()


@router.get("/identity", summary="解析前端身份")
async def get_identity(persona_id: str = "default", project_id: str = "default"):
    return parse_identity(project_id, persona_id)


from __future__ import annotations

from fastapi import APIRouter, Response

from health_payload import build_health_payload, build_readiness_payload
from knowledge.workspace import parse_identity
from safety.observability import get_metrics_store, render_prometheus

router = APIRouter(prefix="/brain", tags=["System"])


@router.get("/health", summary="Liveness probe — 0 queries")
async def health():
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness probe — lightweight DB ping")
async def health_ready():
    return build_readiness_payload()


@router.get("/health/detailed", summary="詳細健康報告（含 DB 狀態、embedding、metrics）")
async def health_detailed(project_id: str = "default"):
    return build_health_payload(project_id)


@router.get("/metrics", summary="大腦層監控指標")
async def metrics():
    return get_metrics_store().snapshot()


@router.get("/metrics/prometheus", summary="Prometheus text exposition format")
async def metrics_prometheus():
    return Response(
        content=render_prometheus(get_metrics_store()),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/identity", summary="解析前端身份")
async def get_identity(persona_id: str = "default", project_id: str = "default"):
    return parse_identity(project_id, persona_id)

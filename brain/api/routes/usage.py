"""Token usage ledger queries (internal; Backend applies account scoping)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.usage import LLMUsage, UsageScope
from infra.usage_ledger import (
    UNIT_TOKENS,
    list_usage_events,
    record_usage_event,
    summarize_usage,
    timeseries_usage,
)
from safety.internal_auth import require_internal_token

router = APIRouter(
    prefix="/brain/usage",
    tags=["Usage"],
    dependencies=[Depends(require_internal_token)],
)


@router.get("/summary", summary="用量彙總")
async def usage_summary(
    group_by: str = Query("model"),
    user_id: str = "",
    principal_type: str = "",
    principal_id: str = "",
    project_id: str = "",
    session_id: str = "",
    kind: str = "",
    since: str = "",
    until: str = "",
) -> dict[str, Any]:
    try:
        return summarize_usage(
            group_by=group_by,
            user_id=user_id,
            principal_type=principal_type,
            principal_id=principal_id,
            project_id=project_id,
            session_id=session_id,
            kind=kind,
            since=since,
            until=until,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/timeseries", summary="用量時間序列")
async def usage_timeseries(
    bucket: str = Query("day"),
    report_timezone: str = "UTC",
    group_by: str = "",
    limit: int = Query(8, ge=1, le=50),
    user_id: str = "",
    principal_type: str = "",
    principal_id: str = "",
    project_id: str = "",
    session_id: str = "",
    kind: str = "",
    since: str = "",
    until: str = "",
) -> dict[str, Any]:
    try:
        return timeseries_usage(
            bucket=bucket,
            report_timezone=report_timezone,
            group_by=group_by,
            limit=limit,
            user_id=user_id,
            principal_type=principal_type,
            principal_id=principal_id,
            project_id=project_id,
            session_id=session_id,
            kind=kind,
            since=since,
            until=until,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/events", summary="用量事件明細")
async def usage_events(
    limit: int = Query(100, ge=1, le=1000),
    user_id: str = "",
    principal_type: str = "",
    principal_id: str = "",
    project_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    kind: str = "",
    since: str = "",
    until: str = "",
) -> dict[str, Any]:
    events = list_usage_events(
        limit=limit,
        user_id=user_id,
        principal_type=principal_type,
        principal_id=principal_id,
        project_id=project_id,
        session_id=session_id,
        trace_id=trace_id,
        kind=kind,
        since=since,
        until=until,
    )
    return {"events": events, "count": len(events)}


class UsageEventIn(BaseModel):
    """One non-LLM usage event forwarded by another service.

    Backend 的 TTS 走這條路徑：帳本由 Brain 單一擁有，跨服務的寫入沿用
    既有的 internal token，而不是讓兩個服務同時開同一個 SQLite 檔。
    """

    provider: str
    model: str = ""
    kind: str = "tts"
    unit_type: str = UNIT_TOKENS
    units: float = 0.0
    latency_ms: float = 0.0
    # 歸屬欄位由呼叫端帶進來；Backend 才知道是哪個帳號／金鑰觸發的。
    user_id: str = ""
    role: str = ""
    principal_type: str = ""
    principal_id: str = ""
    project_id: str = "default"
    session_id: str = ""
    persona_id: str = "default"
    trace_id: str = ""
    channel: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    raw: dict[str, Any] | None = Field(default=None)


@router.post("/events", summary="記錄一筆用量事件（內部）", status_code=201)
async def create_usage_event(payload: UsageEventIn) -> dict[str, Any]:
    if not payload.provider.strip():
        raise HTTPException(status_code=400, detail="provider 不可為空")
    if payload.units < 0:
        raise HTTPException(status_code=400, detail="units 不可為負數")

    scope = UsageScope(
        kind=payload.kind,
        user_id=payload.user_id,
        role=payload.role,
        principal_type=payload.principal_type,
        principal_id=payload.principal_id,
        project_id=payload.project_id or "default",
        session_id=payload.session_id,
        persona_id=payload.persona_id or "default",
        trace_id=payload.trace_id,
        channel=payload.channel,
    )
    event = record_usage_event(
        provider=payload.provider,
        model=payload.model,
        usage=LLMUsage(
            input_tokens=payload.input_tokens,
            output_tokens=payload.output_tokens,
            total_tokens=payload.total_tokens,
        ),
        latency_ms=payload.latency_ms,
        kind=payload.kind,
        scope=scope,
        raw=payload.raw,
        unit_type=payload.unit_type,
        units=payload.units,
    )
    if event is None:
        raise HTTPException(status_code=500, detail="usage ledger write failed")
    return {"recorded": True}

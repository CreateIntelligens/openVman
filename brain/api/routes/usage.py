"""Token usage ledger queries (internal; Backend applies account scoping)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from infra.usage_ledger import list_usage_events, summarize_usage
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
        project_id=project_id,
        session_id=session_id,
        trace_id=trace_id,
        kind=kind,
        since=since,
        until=until,
    )
    return {"events": events, "count": len(events)}

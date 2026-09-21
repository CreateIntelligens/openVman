from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from infra.datetime_utils import utc_now_iso
from memory.memory import (
    delete_session_for_project,
    get_session_store,
    list_sessions_for_project,
)
from protocol.history import serialize_history_messages
from safety.internal_auth import require_internal_token
from safety.observability import log_event, log_exception

router = APIRouter(
    prefix="/brain",
    tags=["Memory & Sessions"],
    dependencies=[Depends(require_internal_token)],
)


# 對話紀錄的保存期限，跟 JTAI 的後台一致：查得到半年，只載得回三個月。
# 兩個數字不同是刻意的——看是為了查問題，下載是把資料帶離系統。
_HISTORY_MAX_MONTHS = 6
_EXPORT_MAX_MONTHS = 3
# 日期以台北時間判斷。用 UTC 會讓早上八點前的「今天」算成昨天，使用者選了
# 今天卻查不到剛剛的對話。
_TZ_TAIPEI = timezone(timedelta(hours=8))


def _months_ago(months: int, base: datetime | None = None) -> date:
    """Return the same day-of-month N months back, clamped to month length.

    3/31 往回一個月沒有 2/31，取當月最後一天。直接減 30*N 天會讓界線隨月份
    長度漂移，使用者看到的「半年」會前後差好幾天。
    """
    base = base or datetime.now(_TZ_TAIPEI)
    year, month = base.year, base.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, min(base.day, calendar.monthrange(year, month)[1]))


def _validate_date_range(
    date_from: str | None,
    date_to: str | None,
    *,
    max_months: int,
    limit_msg: str,
) -> None:
    """Reject ranges that reach past the retention window."""
    minimum = _months_ago(max_months)
    parsed_from: date | None = None
    if date_from:
        try:
            parsed_from = datetime.strptime(date_from, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="無效的開始日期格式，請使用 YYYY-MM-DD",
            ) from exc
        if parsed_from < minimum:
            raise HTTPException(status_code=400, detail=limit_msg)
    if date_to:
        try:
            parsed_to = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="無效的結束日期格式，請使用 YYYY-MM-DD",
            ) from exc
        if parsed_from and parsed_to < parsed_from:
            raise HTTPException(
                status_code=400, detail="結束日期不能早於開始日期",
            )


@router.get("/sessions", summary="列出對話 Session")
async def list_sessions(
    project_id: str = "default",
    persona_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
):
    _validate_date_range(
        date_from, date_to,
        max_months=_HISTORY_MAX_MONTHS,
        limit_msg="查詢區間限制為半年內",
    )
    try:
        sessions = list_sessions_for_project(
            project_id=project_id,
            persona_id=persona_id,
            date_from=date_from,
            date_to=date_to,
            search=search,
        )
    except Exception as exc:
        log_exception("list_sessions_error", exc)
        raise HTTPException(status_code=500, detail="無法讀取 session 列表") from exc
    return {"sessions": sessions, "session_count": len(sessions)}


def _parse_session_ids(raw_session_ids: str | None) -> set[str] | None:
    if raw_session_ids is None:
        return None
    return {
        session_id
        for value in raw_session_ids.split(",")
        if (session_id := value.strip())
    }


@router.get("/sessions/export", summary="匯出對話 Session")
def export_sessions(
    project_id: str = "default",
    persona_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    session_ids: str | None = None,
) -> dict[str, Any]:
    _validate_date_range(
        date_from, date_to,
        max_months=_EXPORT_MAX_MONTHS,
        limit_msg="下載區間限制為近三個月內",
    )
    # 不填起始日就等於從頭撈，那會讓限制形同虛設，所以補上界線。
    date_from = date_from or _months_ago(_EXPORT_MAX_MONTHS).isoformat()
    try:
        store = get_session_store(project_id=project_id)
        summaries = store.list_sessions(
            persona_id=persona_id,
            date_from=date_from,
            date_to=date_to,
            search=search,
        )
        selected_ids = _parse_session_ids(session_ids)
        if selected_ids is not None:
            summaries = [
                summary
                for summary in summaries
                if str(summary["session_id"]) in selected_ids
            ]

        exported_sessions: list[dict[str, Any]] = []
        total_messages = 0
        for summary in summaries:
            summary_persona_id = str(summary["persona_id"])
            messages = serialize_history_messages(
                store.list_messages(
                    str(summary["session_id"]),
                    persona_id=summary_persona_id,
                )
            )
            total_messages += len(messages)
            exported_sessions.append(
                {
                    **summary,
                    "messages": messages,
                }
            )
    except Exception as exc:
        log_exception("export_sessions_error", exc)
        raise HTTPException(status_code=500, detail="無法匯出 session") from exc

    return {
        "exported_at": utc_now_iso(),
        "project_id": project_id,
        "persona_id": persona_id,
        "sessions": exported_sessions,
        "total_messages": total_messages,
        "total_sessions": len(exported_sessions),
    }


@router.delete("/sessions/{session_id}", summary="刪除對話 Session")
async def delete_session(session_id: str, project_id: str = "default"):
    deleted = delete_session_for_project(project_id=project_id, session_id=session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session 不存在")
    log_event("session_deleted", session_id=session_id, project_id=project_id)
    return {"status": "ok", "session_id": session_id}


class RecallToggleBody(BaseModel):
    disabled: bool


@router.post(
    "/sessions/{session_id}/recall-toggle", summary="切換 Session 的 Auto Recall 開關"
)
async def recall_toggle(
    session_id: str, body: RecallToggleBody, project_id: str = "default"
):
    store = get_session_store(project_id=project_id)
    store.set_recall_disabled(session_id, body.disabled)
    log_event(
        "recall_toggled",
        session_id=session_id,
        project_id=project_id,
        disabled=body.disabled,
    )
    return {"session_id": session_id, "recall_disabled": body.disabled}

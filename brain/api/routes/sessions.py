from __future__ import annotations

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


@router.get("/sessions", summary="列出對話 Session")
async def list_sessions(
    project_id: str = "default",
    persona_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
):
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

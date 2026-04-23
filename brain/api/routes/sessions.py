from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from memory.memory import delete_session_for_project, get_session_store, list_sessions_for_project
from safety.observability import log_event, log_exception

router = APIRouter(prefix="/brain", tags=["Memory & Sessions"])


@router.get("/sessions", summary="列出對話 Session")
async def list_sessions(project_id: str = "default", persona_id: str | None = None):
    try:
        sessions = list_sessions_for_project(project_id=project_id, persona_id=persona_id)
    except Exception as exc:
        log_exception("list_sessions_error", exc)
        raise HTTPException(status_code=500, detail="無法讀取 session 列表") from exc
    return {"sessions": sessions, "session_count": len(sessions)}


@router.delete("/sessions/{session_id}", summary="刪除對話 Session")
async def delete_session(session_id: str, project_id: str = "default"):
    deleted = delete_session_for_project(project_id=project_id, session_id=session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session 不存在")
    log_event("session_deleted", session_id=session_id, project_id=project_id)
    return {"status": "ok", "session_id": session_id}


class RecallToggleBody(BaseModel):
    disabled: bool


@router.post("/sessions/{session_id}/recall-toggle", summary="切換 Session 的 Auto Recall 開關")
async def recall_toggle(session_id: str, body: RecallToggleBody, project_id: str = "default"):
    store = get_session_store(project_id=project_id)
    store.set_recall_disabled(session_id, body.disabled)
    log_event("recall_toggled", session_id=session_id, project_id=project_id, disabled=body.disabled)
    return {"session_id": session_id, "recall_disabled": body.disabled}

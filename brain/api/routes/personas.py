from __future__ import annotations

from fastapi import APIRouter, HTTPException

from personas.personas import (
    clone_persona_scaffold,
    create_persona_scaffold,
    delete_persona_scaffold,
    list_personas,
    set_persona_avatar,
)
from protocol.schemas import PersonaAvatarRequest, PersonaCloneRequest, PersonaCreateRequest, PersonaDeleteRequest
from safety.observability import log_event

router = APIRouter(prefix="/brain", tags=["Personas"])


@router.get("/personas", summary="列出人設清單")
async def list_personas_route(project_id: str = "default"):
    items = list_personas(project_id)
    return {"personas": items, "persona_count": len(items)}


@router.post("/personas", summary="建立新人設")
async def create_persona_route(payload: PersonaCreateRequest):
    try:
        result = create_persona_scaffold(payload.persona_id, payload.label, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event("persona_created", persona_id=payload.persona_id, project_id=payload.project_id)
    return result


@router.delete("/personas", summary="刪除人設")
async def delete_persona_route(payload: PersonaDeleteRequest):
    try:
        result = delete_persona_scaffold(payload.persona_id, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event("persona_deleted", persona_id=payload.persona_id, project_id=payload.project_id)
    return result


@router.post("/personas/clone", summary="複製人設")
async def clone_persona_route(payload: PersonaCloneRequest):
    try:
        result = clone_persona_scaffold(payload.source_persona_id, payload.target_persona_id, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event(
        "persona_cloned",
        source_persona_id=payload.source_persona_id,
        target_persona_id=payload.target_persona_id,
        project_id=payload.project_id,
    )
    return result


@router.post("/personas/avatar", summary="綁定 persona 的 Avatar 角色")
async def set_persona_avatar_route(payload: PersonaAvatarRequest):
    try:
        result = set_persona_avatar(payload.persona_id, payload.avatar_char_id, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event(
        "persona_avatar_set",
        persona_id=payload.persona_id,
        avatar_char_id=payload.avatar_char_id,
        project_id=payload.project_id,
    )
    return result


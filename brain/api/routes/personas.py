from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from knowledge.workspace import get_workspace_root, write_text_atomic
from personas.personas import (
    clone_persona_scaffold,
    create_persona_scaffold,
    delete_persona_scaffold,
    list_personas,
    normalize_persona_id,
    set_persona_avatar,
)
from protocol.schemas import (
    PersonaAvatarRequest,
    PersonaCloneRequest,
    PersonaCreateRequest,
    PersonaDeleteRequest,
)
from safety.internal_auth import require_internal_token
from safety.observability import log_event
from safety.vendor_access import VendorRequest, vendor_workspace_path

router = APIRouter(
    prefix="/brain",
    tags=["Personas"],
    dependencies=[Depends(require_internal_token)],
)


@router.get("/personas", summary="列出人設清單")
async def list_personas_route(project_id: str = "default", vendor: VendorRequest = False):
    items = _list_vendor_personas(project_id) if vendor else list_personas(project_id)
    return {"personas": items, "persona_count": len(items)}


def _persona_soul_path(persona_id: str, project_id: str) -> Path:
    try:
        persona_id = normalize_persona_id(persona_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="角色代號格式不正確。") from exc
    relative = "SOUL.md" if persona_id == "default" else f"personas/{persona_id}/SOUL.md"
    path = vendor_workspace_path(project_id, relative, "soul")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="找不到角色的人設內容。")
    return path


def _list_vendor_personas(project_id: str) -> list[dict]:
    root = get_workspace_root(project_id).resolve()
    personas_root = root / "personas"
    directories = personas_root.iterdir() if personas_root.is_dir() and not personas_root.is_symlink() else ()
    items = []
    for persona_id in ("default", *sorted(path.name for path in directories if path.name != "default")):
        try:
            if persona_id != normalize_persona_id(persona_id):
                continue
            path = _persona_soul_path(persona_id, project_id)
            content = path.read_text(encoding="utf-8-sig")
        except (HTTPException, OSError, ValueError):
            continue
        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
        items.append({
            "persona_id": persona_id,
            "label": first_line.lstrip("# ").strip() if first_line.startswith("#") else persona_id,
            "is_default": persona_id == "default",
        })
    return items


class PersonaSoulPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = "default"
    persona_id: str = "default"
    content: str


@router.get("/personas/soul", summary="讀取角色的 SOUL.md")
def get_persona_soul(persona_id: str = "default", project_id: str = "default"):
    path = _persona_soul_path(persona_id, project_id)
    return {"content": path.read_text(encoding="utf-8-sig")}


@router.put("/personas/soul", summary="儲存角色的 SOUL.md")
def put_persona_soul(payload: PersonaSoulPut):
    path = _persona_soul_path(payload.persona_id, payload.project_id)
    write_text_atomic(path, payload.content)
    return {"status": "ok"}


@router.post("/personas", summary="建立新人設")
async def create_persona_route(payload: PersonaCreateRequest):
    try:
        result = create_persona_scaffold(
            payload.persona_id,
            payload.label,
            payload.project_id,
        )
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
        result = clone_persona_scaffold(
            payload.source_persona_id,
            payload.target_persona_id,
            payload.project_id,
        )
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
        result = set_persona_avatar(
            payload.persona_id,
            payload.avatar_char_id,
            payload.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event(
        "persona_avatar_set",
        persona_id=payload.persona_id,
        avatar_char_id=payload.avatar_char_id,
        project_id=payload.project_id,
    )
    return result

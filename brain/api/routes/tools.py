from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from infra.project_context import normalize_project_id
from protocol.schemas import SkillCreateRequest, SkillFilesUpdateRequest
from safety.internal_auth import require_internal_token
from tools.skill import SkillRef, SkillScope, is_valid_skill_id
from tools.skill_manager import get_skill_manager
from tools.tool_registry import (
    activate_project_sync,
    invalidate_skill_tools_sync,
)

router = APIRouter(
    prefix="/brain",
    tags=["Tools & Skills"],
    dependencies=[Depends(require_internal_token)],
)


def _skill_deps(project_id: str = "default") -> tuple[Any, Any]:
    return activate_project_sync(project_id), get_skill_manager()


def _normalized_project_id(project_id: str | None) -> str | None:
    # Backend 用正規化後（去空白、default 換成預設專案）的 ID 授權；技能目錄必須用
    # 同一個 ID，否則授權的是一個專案、寫入的是另一個目錄。
    if not project_id:
        return None
    try:
        normalized = normalize_project_id(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 格式規則允許點，「.」「..」會讓專案技能目錄指到專案資料夾外面。
    if normalized in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid project_id")
    return normalized


def _parse_scope(scope: str | None, project_id: str | None) -> tuple[SkillScope | None, str | None]:
    if scope not in (None, "shared", "project"):
        raise HTTPException(status_code=400, detail=f"invalid scope: {scope}")
    project_id = _normalized_project_id(project_id)
    if scope == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project scope requires project_id")
    return scope, project_id  # type: ignore[return-value]


def skill_ref(
    skill_id: str,
    scope: str | None = Query(None),
    project_id: str | None = Query(None),
) -> SkillRef:
    if not is_valid_skill_id(skill_id):
        raise HTTPException(status_code=422, detail=f"invalid skill id: {skill_id!r}")
    parsed_scope, parsed_project_id = _parse_scope(scope, project_id)
    return SkillRef(skill_id=skill_id, scope=parsed_scope, project_id=parsed_project_id)


@router.get("/tools", summary="列出工具與技能")
async def list_tools(project_id: str = Query("default")):
    project_id = _normalized_project_id(project_id) or _normalized_project_id("default")
    registry, manager = _skill_deps(project_id)
    all_tools = registry.list_tools()

    def serialize(tool: Any) -> dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }

    builtin_tools = [serialize(tool) for tool in all_tools if ":" not in tool.name]
    skill_tools = [serialize(tool) for tool in all_tools if ":" in tool.name]
    skills = [
        {
            "id": skill.manifest.id,
            "name": skill.manifest.name,
            "description": skill.manifest.description,
            "version": skill.manifest.version,
            "scope": skill.scope,
            "project_id": skill.project_id,
            "enabled": skill.enabled,
            "tools": [tool.name for tool in skill.manifest.tools],
            "warnings": skill.warnings,
        }
        for skill in manager.list_skills(project_id)
    ]
    return {"tools": builtin_tools, "skill_tools": skill_tools, "skills": skills}


@router.patch("/skills/{skill_id}/toggle", summary="切換技能啟用狀態")
async def toggle_skill(ref: SkillRef = Depends(skill_ref)):
    registry, manager = _skill_deps(ref.project_id or "default")
    try:
        skill = manager.toggle_skill(ref, registry)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    invalidate_skill_tools_sync()
    return {
        "status": "ok",
        "skill_id": ref.skill_id,
        "scope": skill.scope,
        "project_id": skill.project_id,
        "enabled": skill.enabled,
    }


@router.post("/skills", summary="建立新技能")
async def create_skill(payload: SkillCreateRequest):
    scope, project_id = _parse_scope(payload.scope, payload.project_id)
    ref = SkillRef(skill_id=payload.skill_id, scope=scope or "shared", project_id=project_id)
    registry, manager = _skill_deps(project_id or "default")
    try:
        skill = manager.create_skill(
            ref,
            name=payload.name,
            description=payload.description,
            registry=registry,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    invalidate_skill_tools_sync()
    return {
        "status": "ok",
        "skill_id": skill.manifest.id,
        "name": skill.manifest.name,
        "scope": skill.scope,
        "project_id": skill.project_id,
        "warnings": skill.warnings,
    }


@router.get("/skills/{skill_id}/files", summary="取得技能檔案")
async def get_skill_files(ref: SkillRef = Depends(skill_ref)):
    _, manager = _skill_deps(ref.project_id or "default")
    try:
        files = manager.get_skill_files(ref)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"skill_id": ref.skill_id, "scope": ref.scope, "project_id": ref.project_id, "files": files}


@router.put("/skills/{skill_id}/files", summary="更新技能檔案")
async def update_skill_files(
    payload: SkillFilesUpdateRequest,
    ref: SkillRef = Depends(skill_ref),
):
    registry, manager = _skill_deps(ref.project_id or "default")
    try:
        skill = manager.update_skill_files(ref, payload.files, registry)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    invalidate_skill_tools_sync()
    return {
        "status": "ok",
        "skill_id": skill.manifest.id,
        "scope": skill.scope,
        "project_id": skill.project_id,
        "enabled": skill.enabled,
        "warnings": skill.warnings,
    }


@router.delete("/skills/{skill_id}", summary="刪除技能")
async def delete_skill(ref: SkillRef = Depends(skill_ref)):
    registry, manager = _skill_deps(ref.project_id or "default")
    try:
        manager.delete_skill(ref, registry)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    invalidate_skill_tools_sync()
    return {"status": "ok", "skill_id": ref.skill_id, "scope": ref.scope, "project_id": ref.project_id}


@router.post("/skills/reload", summary="重新載入所有技能")
async def reload_all_skills(project_id: str = Query("default")):
    project_id = _normalized_project_id(project_id) or _normalized_project_id("default")
    registry, manager = _skill_deps(project_id)
    skills = manager.reload_all(registry, project_id=project_id)
    invalidate_skill_tools_sync()
    all_warnings = {skill.manifest.id: skill.warnings for skill in skills if skill.warnings}
    return {
        "status": "ok",
        "skills_count": len(skills),
        "skills": [skill.manifest.id for skill in skills],
        "warnings": all_warnings,
    }

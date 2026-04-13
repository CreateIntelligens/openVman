from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from protocol.schemas import SkillCreateRequest, SkillFilesUpdateRequest
from tools.skill_manager import get_skill_manager
from tools.tool_registry import get_tool_registry

router = APIRouter(prefix="/brain", tags=["Tools & Skills"])


def _skill_deps() -> tuple[Any, Any]:
    return get_tool_registry(), get_skill_manager()


@router.get("/tools", summary="列出工具與技能")
async def list_tools():
    registry, manager = _skill_deps()
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
            "enabled": skill.enabled,
            "tools": [tool.name for tool in skill.manifest.tools],
            "warnings": skill.warnings,
        }
        for skill in manager.list_skills()
    ]
    return {"tools": builtin_tools, "skill_tools": skill_tools, "skills": skills}


@router.patch("/skills/{skill_id}/toggle", summary="切換技能啟用狀態")
async def toggle_skill(skill_id: str):
    registry, manager = _skill_deps()
    try:
        skill = manager.toggle_skill(skill_id, registry)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "skill_id": skill_id, "enabled": skill.enabled}


@router.post("/skills", summary="建立新技能")
async def create_skill(payload: SkillCreateRequest):
    registry, manager = _skill_deps()
    try:
        skill = manager.create_skill(payload.skill_id, payload.name, payload.description, registry)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "ok",
        "skill_id": skill.manifest.id,
        "name": skill.manifest.name,
        "warnings": skill.warnings,
    }


@router.get("/skills/{skill_id}/files", summary="取得技能檔案")
async def get_skill_files(skill_id: str):
    _registry, manager = _skill_deps()
    try:
        files = manager.get_skill_files(skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"skill_id": skill_id, "files": files}


@router.put("/skills/{skill_id}/files", summary="更新技能檔案")
async def update_skill_files(skill_id: str, payload: SkillFilesUpdateRequest):
    registry, manager = _skill_deps()
    try:
        skill = manager.update_skill_files(skill_id, payload.files, registry)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "ok",
        "skill_id": skill.manifest.id,
        "enabled": skill.enabled,
        "warnings": skill.warnings,
    }


@router.delete("/skills/{skill_id}", summary="刪除技能")
async def delete_skill(skill_id: str):
    registry, manager = _skill_deps()
    try:
        manager.delete_skill(skill_id, registry)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "skill_id": skill_id}


@router.post("/skills/reload", summary="重新載入所有技能")
async def reload_all_skills():
    registry, manager = _skill_deps()
    skills = manager.reload_all(registry)
    all_warnings = {skill.manifest.id: skill.warnings for skill in skills if skill.warnings}
    return {
        "status": "ok",
        "skills_count": len(skills),
        "skills": [skill.manifest.id for skill in skills],
        "warnings": all_warnings,
    }


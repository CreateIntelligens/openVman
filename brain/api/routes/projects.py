from __future__ import annotations

from fastapi import APIRouter, HTTPException

from infra.project_admin import create_project, delete_project, get_project_info, list_projects
from protocol.schemas import ProjectCreateRequest, ProjectDeleteRequest
from safety.observability import log_event

router = APIRouter(prefix="/brain", tags=["Projects"])


@router.get("/projects", summary="列出所有專案")
async def list_projects_route():
    projects = list_projects()
    return {"projects": projects, "project_count": len(projects)}


@router.post("/projects", summary="建立新專案")
async def create_project_route(payload: ProjectCreateRequest):
    try:
        result = create_project(payload.label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event("project_created", project_id=result["project_id"])
    return result


@router.delete("/projects", summary="刪除專案")
async def delete_project_route(payload: ProjectDeleteRequest):
    try:
        result = delete_project(payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event("project_deleted", project_id=payload.project_id)
    return result


@router.get("/projects/{project_id}", summary="取得單一專案資訊")
async def get_project_route(project_id: str):
    try:
        return get_project_info(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


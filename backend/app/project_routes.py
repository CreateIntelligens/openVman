"""Account-scoped project facade backed by the Brain service."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.responses import Response

from app.auth.dependencies import CurrentAccount, get_current_account, require_admin
from app.auth.models import ResourceType, ResourceVisibility
from app.auth.repositories import ResourceConflictError
from app.auth.resources import (
    ResourceAccess,
    ResourceNotFoundError,
    list_accessible_resources,
    resolve_resource,
)
from app.auth.runtime import AuthRuntime, get_auth_runtime
from app.brain_proxy import proxy_to_brain

logger = logging.getLogger("backend.project_routes")

router = APIRouter(tags=["Brain / Projects"])
_PROJECT_PATH = "projects"
_RESOURCE_NOT_FOUND_DETAIL = "Resource not found"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCreateRequest(_StrictModel):
    label: str = Field(min_length=1)

    @field_validator("label")
    @classmethod
    def label_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("專案名稱不可為空白")
        return value


class ProjectDeleteRequest(_StrictModel):
    project_id: str = Field(min_length=1)


def _resource_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_RESOURCE_NOT_FOUND_DETAIL,
    )


def _resolve_project(
    runtime: AuthRuntime,
    current: CurrentAccount,
    project_id: str,
    *,
    access: ResourceAccess,
) -> None:
    try:
        resolve_resource(
            runtime.resources,
            current.user,
            ResourceType.PROJECT,
            project_id,
            access=access,
        )
    except ResourceNotFoundError as exc:
        raise _resource_not_found() from exc


def _json_object(response: Response) -> dict[str, Any] | None:
    body = getattr(response, "body", None)
    if not isinstance(body, bytes):
        return None
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_success(response: Response) -> bool:
    return 200 <= response.status_code < 300


def _replacement_request(
    request: Request,
    *,
    method: str,
    payload: dict[str, str],
) -> Request:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    scope = dict(request.scope)
    scope["method"] = method
    scope["query_string"] = b""

    async def receive() -> dict[str, object]:
        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }

    return Request(scope, receive)


async def _compensate_project_creation(
    request: Request,
    current: CurrentAccount,
    project_id: str,
) -> bool:
    compensation_request = _replacement_request(
        request,
        method="DELETE",
        payload={"project_id": project_id},
    )
    try:
        response = await proxy_to_brain(
            compensation_request,
            _PROJECT_PATH,
            current=current,
            project_id=project_id,
        )
    except Exception:
        logger.exception(
            "project ownership compensation request failed project_id=%s",
            project_id,
        )
        return False
    return _is_success(response)


@router.get("/api/projects", summary="List Projects")
async def list_projects(
    request: Request,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> Response:
    response = await proxy_to_brain(
        request,
        _PROJECT_PATH,
        current=current,
    )
    if not _is_success(response):
        return response

    payload = _json_object(response)
    if payload is None or not isinstance(payload.get("projects"), list):
        logger.error("brain returned an invalid project list response")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": "Invalid project service response"},
        )

    accessible_ids = {
        resource.resource_id
        for resource in list_accessible_resources(
            runtime.resources,
            current.user,
            ResourceType.PROJECT,
        )
    }
    projects = [
        project
        for project in payload["projects"]
        if isinstance(project, dict)
        and isinstance(project.get("project_id"), str)
        and project["project_id"] in accessible_ids
    ]
    return JSONResponse(
        status_code=response.status_code,
        content={**payload, "projects": projects, "project_count": len(projects)},
    )


@router.post("/api/projects", summary="Create Project")
async def create_project(
    _body: ProjectCreateRequest,
    request: Request,
    current: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> Response:
    response = await proxy_to_brain(
        request,
        _PROJECT_PATH,
        current=current,
    )
    if not _is_success(response):
        return response

    payload = _json_object(response)
    project_id = payload.get("project_id") if payload is not None else None
    if not isinstance(project_id, str) or not project_id:
        logger.error("brain returned an invalid project creation response")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": "Invalid project service response"},
        )

    try:
        runtime.resources.register(
            resource_type=ResourceType.PROJECT,
            resource_id=project_id,
            owner_user_id=current.user.id,
            visibility=ResourceVisibility.PRIVATE,
            metadata={"label": payload.get("label", "")},
        )
    except Exception as exc:
        compensated = await _compensate_project_creation(
            request,
            current,
            project_id,
        )
        logger.error(
            "project ownership registration failed project_id=%s compensated=%s",
            project_id,
            compensated,
            exc_info=exc,
        )
        response_status = (
            status.HTTP_409_CONFLICT
            if isinstance(exc, ResourceConflictError)
            else status.HTTP_502_BAD_GATEWAY
        )
        return JSONResponse(
            status_code=response_status,
            content={"detail": "Project ownership registration failed"},
        )
    return response


@router.delete("/api/projects", summary="Delete Project")
async def delete_project(
    body: ProjectDeleteRequest,
    request: Request,
    current: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> Response:
    _resolve_project(
        runtime,
        current,
        body.project_id,
        access=ResourceAccess.MUTATE,
    )
    response = await proxy_to_brain(
        request,
        _PROJECT_PATH,
        current=current,
        project_id=body.project_id,
    )
    if not _is_success(response):
        return response

    try:
        removed = runtime.resources.unregister(
            ResourceType.PROJECT,
            body.project_id,
        )
    except Exception as exc:
        logger.error(
            "project ownership cleanup failed project_id=%s",
            body.project_id,
            exc_info=exc,
        )
        removed = False
    if not removed:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Project ownership cleanup failed"},
        )
    return response


@router.get("/api/projects/{project_id}", summary="Get Project")
async def get_project(
    project_id: str,
    request: Request,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> Response:
    _resolve_project(
        runtime,
        current,
        project_id,
        access=ResourceAccess.READ,
    )
    return await proxy_to_brain(
        request,
        f"projects/{project_id}",
        current=current,
        project_id=project_id,
    )

"""Account-scoped project facade backed by the Brain service."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.responses import Response

from app.auth.dependencies import (
    CurrentAccount,
    get_current_account,
    require_admin,
    require_root,
)
from app.auth.models import ProjectPolicyRecord, ResourceType, ResourceVisibility
from app.auth.project_resources import (
    effective_project_default,
    effective_project_resources,
)
from app.auth.repository_errors import (
    InvalidProjectPolicyError,
    ResourceConflictError,
)
from app.auth.resources import (
    ResourceAccess,
    ResourceNotFoundError,
    list_accessible_resources,
    resolve_admin_scope,
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


@router.get("/api/v1/projects", summary="List Projects")
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


@router.post("/api/v1/projects", summary="Create Project")
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


@router.delete("/api/v1/projects", summary="Delete Project")
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


@router.get("/api/v1/projects/{project_id}", summary="Get Project")
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


class ProjectPolicyPayload(_StrictModel):
    """A project's resource and voice limits; empty lists mean no project restriction."""

    allowed_asr_engines: list[str] = Field(default_factory=list)
    default_asr_engine: str | None = None
    taiwanese_asr_engine: str | None = None
    allowed_tts_voices: list[str] = Field(default_factory=list)
    default_tts_voice: str | None = None
    allowed_characters: list[str] = Field(default_factory=list)
    default_character_id: str | None = None
    allowed_backgrounds: list[str] = Field(default_factory=list)
    default_background_id: str | None = None
    allowed_mascots: list[str] = Field(default_factory=list)
    default_mascot_id: str | None = None
    tts_engine_order: list[str] = Field(
        default_factory=list,
        description="沒指定引擎與聲音時的 TTS 嘗試順序（indextts、indextts-nurse、voxcpm、cosyvoice、gemini-tts、gcp-tts、aws-polly、edge-tts）；空的用部署順序",
    )
    asr_engine_order: list[str] = Field(
        default_factory=list,
        description="批次 ASR 備援順序（呼叫端指定的引擎之後）；有允許清單時必須是其子集；空的用部署順序",
    )


class ProjectPolicyProfile(ProjectPolicyPayload):
    project_id: str
    updated_by: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_record(cls, record: ProjectPolicyRecord) -> ProjectPolicyProfile:
        return cls(
            project_id=record.project_id,
            allowed_asr_engines=list(record.allowed_asr_engines),
            default_asr_engine=record.default_asr_engine,
            taiwanese_asr_engine=record.taiwanese_asr_engine,
            allowed_tts_voices=list(record.allowed_tts_voices),
            default_tts_voice=record.default_tts_voice,
            allowed_characters=list(record.allowed_characters),
            default_character_id=record.default_character_id,
            allowed_backgrounds=list(record.allowed_backgrounds),
            default_background_id=record.default_background_id,
            allowed_mascots=list(record.allowed_mascots),
            default_mascot_id=record.default_mascot_id,
            tts_engine_order=list(record.tts_engine_order),
            asr_engine_order=list(record.asr_engine_order),
            updated_by=record.updated_by,
            updated_at=record.updated_at,
        )


@router.get(
    "/api/v1/projects/{project_id}/policy",
    response_model=ProjectPolicyProfile,
    responses={404: {"description": "查無此專案或沒有編輯權限"}},
    summary="Get Project Resource Policy",
)
def get_project_policy(
    project_id: str,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> ProjectPolicyProfile:
    """能編輯專案內容的人都能看；改設定只有管理者。"""
    _resolve_project(runtime, current, project_id, access=ResourceAccess.EDIT)
    return ProjectPolicyProfile.from_record(runtime.project_policies.get(project_id))


@router.put(
    "/api/v1/projects/{project_id}/policy",
    response_model=ProjectPolicyProfile,
    responses={
        403: {"description": "需要管理者，或選了超出自己可指派範圍的資源"},
        404: {"description": "查無此專案或不在管理範圍內"},
        422: {"description": "資源不存在，或預設值不在允許清單內"},
    },
    summary="Replace Project Resource Policy",
)
def put_project_policy(
    project_id: str,
    body: ProjectPolicyPayload,
    current: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> ProjectPolicyProfile:
    """整份取代；全部留空等於移除專案限制。"""
    _resolve_project(runtime, current, project_id, access=ResourceAccess.MUTATE)
    scope = resolve_admin_scope(current.user, runtime.admin_scopes)
    assigned_or_project = {
        (ResourceType(r.resource_type), r.resource_id)
        for r in runtime.project_resource_assignments.list_for_project(project_id)
    } | {
        (r.resource_type, r.resource_id)
        for r in runtime.resources.list_by_owner_project(project_id)
    }
    requested = [
        *(
            (ResourceType.ASR_ENGINE, engine)
            for engine in (
                *body.allowed_asr_engines,
                body.default_asr_engine,
                body.taiwanese_asr_engine,
            )
            if engine and engine.strip()
        ),
        *(
            (ResourceType.CUSTOM_VOICE, voice)
            for voice in (*body.allowed_tts_voices, body.default_tts_voice)
            if voice and voice.strip()
        ),
        *(
            (ResourceType.AVATAR_CHARACTER, char)
            for char in (*body.allowed_characters, body.default_character_id)
            if char and char.strip()
        ),
        *(
            (ResourceType.AVATAR_BACKGROUND, bg)
            for bg in (*body.allowed_backgrounds, body.default_background_id)
            if bg and bg.strip()
        ),
        *(
            (ResourceType.AVATAR_MASCOT, mascot)
            for mascot in (*body.allowed_mascots, body.default_mascot_id)
            if mascot and mascot.strip()
        ),
    ]
    outside = sorted({
        f"{resource_type.value}/{resource_id.strip()}"
        for resource_type, resource_id in requested
        if (resource_type, resource_id.strip()) not in assigned_or_project
        and not scope.allows(resource_type, resource_id.strip())
    })
    if outside:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cannot use resources outside your assigned scope: "
            + ", ".join(outside),
        )
    try:
        record = runtime.project_policies.replace(
            project_id=project_id,
            allowed_asr_engines=body.allowed_asr_engines,
            default_asr_engine=body.default_asr_engine,
            taiwanese_asr_engine=body.taiwanese_asr_engine,
            allowed_tts_voices=body.allowed_tts_voices,
            default_tts_voice=body.default_tts_voice,
            allowed_characters=body.allowed_characters,
            default_character_id=body.default_character_id,
            allowed_backgrounds=body.allowed_backgrounds,
            default_background_id=body.default_background_id,
            allowed_mascots=body.allowed_mascots,
            default_mascot_id=body.default_mascot_id,
            tts_engine_order=body.tts_engine_order,
            asr_engine_order=body.asr_engine_order,
            updated_by=current.user.id,
        )
    except InvalidProjectPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    logger.info(
        "project policy updated project_id=%s by=%s asr=%s tts=%s chars=%s",
        project_id,
        current.user.id,
        ",".join(record.allowed_asr_engines) or "-",
        ",".join(record.allowed_tts_voices) or "-",
        ",".join(record.allowed_characters) or "-",
    )
    return ProjectPolicyProfile.from_record(record)


@router.get(
    "/api/v1/projects/{project_id}/resources",
    summary="Get Project Effective Resources",
)
def get_project_resources(
    project_id: str,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, Any]:
    """回傳該專案每種資源的可用清單與預設值（以呼叫者身分計算）。"""
    _resolve_project(runtime, current, project_id, access=ResourceAccess.READ)
    account = None if current.embed_key is not None else current.user

    resource_types = [
        ResourceType.AVATAR_CHARACTER,
        ResourceType.AVATAR_BACKGROUND,
        ResourceType.AVATAR_MASCOT,
        ResourceType.CUSTOM_VOICE,
        ResourceType.ASR_ENGINE,
    ]

    result: dict[str, Any] = {}
    defaults: dict[str, Any] = {}
    for res_type in resource_types:
        entries = effective_project_resources(
            runtime, account, project_id, res_type
        )
        default_id = effective_project_default(
            runtime, account, project_id, res_type, available_entries=entries
        )
        assignments = {
            a.resource_id: a
            for a in runtime.project_resource_assignments.list_for_project(
                project_id, resource_type=res_type
            )
        }
        items = []
        for e in entries:
            item: dict[str, Any] = {
                "resource_id": e.resource_id,
                "label": e.label,
                "source": e.source,
                "is_default": e.resource_id == default_id,
                "in_project_scope": e.in_project_scope,
            }
            if e.resource_id in assignments:
                a = assignments[e.resource_id]
                item["assigned_at"] = a.assigned_at
                item["assigned_by"] = a.assigned_by
            items.append(item)

        result[res_type.value] = items
        defaults[res_type.value] = default_id

    result["defaults"] = defaults
    return result


class ProjectResourceAssignmentRequest(_StrictModel):
    resource_type: ResourceType
    resource_id: str


@router.post(
    "/api/v1/projects/{project_id}/assignments",
    summary="Assign Resource to Project (ROOT only)",
)
def assign_project_resource(
    project_id: str,
    body: ProjectResourceAssignmentRequest,
    current: CurrentAccount = Depends(require_root),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, Any]:
    project = runtime.resources.get(ResourceType.PROJECT, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_RESOURCE_NOT_FOUND_DETAIL,
        )
    resource = runtime.resources.get(body.resource_type, body.resource_id)
    if resource is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Resource not found: {body.resource_type.value}/{body.resource_id}",
        )
    record = runtime.project_resource_assignments.assign(
        project_id=project_id,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        assigned_by=current.user.id,
    )
    return {
        "status": "ok",
        "assignment": {
            "project_id": record.project_id,
            "resource_type": record.resource_type.value,
            "resource_id": record.resource_id,
            "assigned_by": record.assigned_by,
            "assigned_at": record.assigned_at,
        },
    }


@router.delete(
    "/api/v1/projects/{project_id}/assignments/{resource_type}/{resource_id}",
    summary="Unassign Resource from Project (ROOT only)",
)
def unassign_project_resource(
    project_id: str,
    resource_type: ResourceType,
    resource_id: str,
    current: CurrentAccount = Depends(require_root),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, Any]:
    deleted = runtime.project_resource_assignments.unassign(
        project_id=project_id,
        resource_type=resource_type,
        resource_id=resource_id,
        unassigned_by=current.user.id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found",
        )
    return {"status": "ok"}

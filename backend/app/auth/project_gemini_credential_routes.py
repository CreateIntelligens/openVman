"""ROOT-only management of a project's Gemini credential."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
)
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
)

from .dependencies import CurrentAccount, require_root
from .model_provider_repository import ModelProviderEncryptionUnavailable
from .model_provider_routes import _brain_post
from .models import ResourceType
from .project_gemini_credentials import (
    project_gemini_metadata,
    project_gemini_repository,
)
from .runtime import AuthRuntime, get_auth_runtime


class _SecretSafeRoute(APIRoute):
    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as exc:
                # 缺 label 等錯誤會把整份 body 放進 input，連 SecretStr 都來不及遮。
                raise HTTPException(
                    status_code=422,
                    detail="invalid project Gemini credential request",
                ) from exc

        return handle


router = APIRouter(
    prefix="/api/v1/projects/{project_id}/gemini-credential",
    tags=["Projects"],
    route_class=_SecretSafeRoute,
)


class UpdateProjectGeminiCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=128)
    # 手動驗證長度，避免 Pydantic 的錯誤 input 欄位回傳完整金鑰。
    api_key: SecretStr = Field(json_schema_extra={"maxLength": 4096})


def _require_project(runtime: AuthRuntime, project_id: str) -> None:
    if runtime.resources.get(ResourceType.PROJECT, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")


@router.get("")
def get_project_gemini_credential(
    project_id: str,
    _actor: Annotated[CurrentAccount, Depends(require_root)],
    runtime: Annotated[AuthRuntime, Depends(get_auth_runtime)],
) -> dict[str, object]:
    _require_project(runtime, project_id)
    return project_gemini_metadata(runtime, project_id)


@router.put("")
def update_project_gemini_credential(
    project_id: str,
    body: UpdateProjectGeminiCredential,
    actor: Annotated[CurrentAccount, Depends(require_root)],
    runtime: Annotated[AuthRuntime, Depends(get_auth_runtime)],
) -> dict[str, object]:
    _require_project(runtime, project_id)
    try:
        project_gemini_repository(runtime).put(
            project_id,
            label=body.label,
            api_key=body.api_key.get_secret_value(),
            actor_id=actor.user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ModelProviderEncryptionUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="model credential encryption is unavailable",
        ) from exc
    refreshed = _brain_post(
        runtime, "/brain/internal/model-providers/refresh",
    ) is not None
    return {
        **project_gemini_metadata(runtime, project_id),
        "runtime_refreshed": refreshed,
    }


@router.delete("")
def delete_project_gemini_credential(
    project_id: str,
    actor: Annotated[CurrentAccount, Depends(require_root)],
    runtime: Annotated[AuthRuntime, Depends(get_auth_runtime)],
) -> dict[str, object]:
    _require_project(runtime, project_id)
    project_gemini_repository(runtime).delete(
        project_id, actor_id=actor.user.id,
    )
    refreshed = _brain_post(
        runtime, "/brain/internal/model-providers/refresh",
    ) is not None
    return {
        **project_gemini_metadata(runtime, project_id),
        "runtime_refreshed": refreshed,
    }

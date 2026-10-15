"""Discover the caller's resources using the existing scoped list endpoints."""

from __future__ import annotations

import json
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app import project_routes, voice_policy
from app.auth.dependencies import CurrentAccount, get_current_account
from app.auth.models import AccountRole, ResourceType
from app.auth.project_resources import effective_project_resources
from app.auth.resources import (
    ResourceAccess,
    ResourceNotFoundError,
    resolve_resource,
)
from app.auth.runtime import AuthRuntime, get_auth_runtime
from app.auth.settings_repository import (
    BROWSER_ASR_PROVIDER,
    SERVER_ASR_PROVIDERS,
    STREAM_ASR_PROVIDERS,
)
from app.auth.settings_routes import get_my_asr_provider
from app.auth.voice_access import resolve_tts_voice
from app.gateway.asr_stream import configured_stream_engines
from app.gateway.ingestion_audio import configured_providers
from app.routes import admin, avatar, backgrounds, mascots

router = APIRouter(tags=["Account"])


class CapabilityAccount(BaseModel):
    id: str
    username: str
    role: str


class CapabilityDefaults(BaseModel):
    project_id: str = ""
    character_id: str = ""
    voice_provider: str = ""
    voice_id: str = ""
    mascot_id: str = ""
    background_id: str = ""


class ServerAsrCapability(BaseModel):
    id: str
    configured: bool
    in_project_scope: bool | None = None


class BrowserAsrCapability(BaseModel):
    id: str
    configured: None = None
    in_project_scope: bool | None = None


class AsrCapabilities(BaseModel):
    value: str
    effective: str
    allowed: list[str]
    batch: list[ServerAsrCapability]
    stream: list[ServerAsrCapability]
    browser: list[BrowserAsrCapability]


class TtsCapabilities(BaseModel):
    providers: list[dict[str, Any]]


class ProjectPolicyCapability(BaseModel):
    """The project's own limits plus what they leave this account."""

    project_id: str
    # 專案設定本身；空清單代表不限制。
    allowed_asr_engines: list[str]
    default_asr_engine: str | None
    taiwanese_asr_engine: str | None
    allowed_tts_voices: list[str]
    default_tts_voice: str | None
    # 這個帳號在這個專案沒指定聲音時會用的聲音（""：交給下游預設）。
    effective_tts_voice: str
    allowed_characters: list[str] | None = None
    default_character_id: str | None = None
    allowed_backgrounds: list[str] | None = None
    default_background_id: str | None = None
    allowed_mascots: list[str] | None = None
    default_mascot_id: str | None = None


class AccountCapabilities(BaseModel):
    schema_version: Literal[1] = 1
    account: CapabilityAccount
    defaults: CapabilityDefaults
    projects: list[dict[str, Any]]
    characters: list[dict[str, Any]]
    mascots: list[dict[str, Any]]
    backgrounds: list[dict[str, Any]]
    tts: TtsCapabilities
    asr: AsrCapabilities
    # 只有帶 project_id 查詢時才出現；沒帶時回應跟以前一模一樣。
    project_policy: ProjectPolicyCapability | None = None


@router.get(
    "/api/v1/me/capabilities",
    response_model=AccountCapabilities,
    responses={
        403: {"description": "不接受 Embed key"},
        404: {"description": "帶了 project_id 但查無此專案或沒有權限"},
        502: {"description": "專案服務回應失敗或格式無效"},
        503: {"description": "專案服務暫時無法連線"},
    },
    summary="取得目前帳號的串接能力與授權資源",
)
async def get_capabilities(
    request: Request,
    project_id: str = "",
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> Response:
    """帶 ``project_id`` 時，ASR 與 TTS 清單改成「帳號授權 ∩ 專案限制」。"""
    if current.embed_key is not None:
        # Embed keys bind a narrower set than their owner's account grants.
        raise HTTPException(
            status_code=403,
            detail="Account capabilities are unavailable to embed keys",
        )
    project_id = project_id.strip()
    policy = None
    if project_id:
        try:
            resolve_resource(
                runtime.resources,
                current.user,
                ResourceType.PROJECT,
                project_id,
                access=ResourceAccess.READ,
            )
        except ResourceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Resource not found") from exc
        policy = runtime.project_policies.get(project_id)

    try:
        projects = await project_routes.list_projects(
            request, current, runtime,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503, detail="Project service unavailable",
        ) from exc
    if projects.status_code != 200:
        raise HTTPException(
            status_code=503 if projects.status_code == 503 else 502,
            detail="Unable to discover projects from project service",
        )
    try:
        project_payload = json.loads(projects.body)
        project_list = project_payload["projects"]
        if not isinstance(project_list, list):
            raise ValueError("invalid project list")
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502, detail="Invalid project service response",
        ) from exc

    characters = await avatar.list_characters(
        project_id=project_id or None, current=current, runtime=runtime
    )
    mascot_list = await mascots.list_mascots(
        project_id=project_id or None, current=current, runtime=runtime
    )
    background_list = await backgrounds.list_backgrounds(
        project_id=project_id or None, current=current, runtime=runtime
    )
    tts_providers = await admin.get_tts_providers(
        current, runtime, project_id=project_id,
    )
    is_root = current.user.role is AccountRole.ROOT
    asr = get_my_asr_provider(current, runtime)
    assigned_asr: list[str] = []
    if project_id:
        assigned_asr = [
            e.resource_id
            for e in effective_project_resources(
                runtime, current.user, project_id, ResourceType.ASR_ENGINE
            )
            if e.source in ("project", "assigned")
        ]
    base_allowed = asr.allowed
    if policy is not None and not is_root:
        asr_allowed = [engine for engine in base_allowed if policy.allows_asr(engine)]
    else:
        asr_allowed = list(base_allowed)
    for engine in assigned_asr:
        if engine not in asr_allowed:
            asr_allowed.append(engine)

    in_scope_asr: set[str] = set()
    if project_id:
        if policy is not None and policy.restricts_asr:
            in_scope_asr = set(policy.allowed_asr_engines) | set(assigned_asr)
        else:
            in_scope_asr = set(asr_allowed)

    asr_effective = (
        voice_policy.effective_asr_engine(
            runtime, current.user, policy, project_id=project_id or None
        )
        if (policy is not None or project_id) else asr.effective
    )
    batch_configured = set(configured_providers())
    stream_configured = set(configured_stream_engines())
    defaults = runtime.account_access.get_defaults(current.user.id)

    capabilities = AccountCapabilities(
        account=CapabilityAccount(
            id=current.user.id,
            username=current.user.username,
            role=current.user.role.value,
        ),
        defaults=CapabilityDefaults(**{
            field: getattr(defaults, field, "")
            for field in CapabilityDefaults.model_fields
        }),
        projects=project_list,
        characters=characters["characters"],
        mascots=mascot_list["mascots"],
        backgrounds=background_list["backgrounds"],
        tts=TtsCapabilities(providers=json.loads(tts_providers.body)),
        asr=AsrCapabilities(
            value=asr.value,
            effective=asr_effective,
            allowed=asr_allowed,
            batch=[
                ServerAsrCapability(
                    id=engine,
                    configured=engine in batch_configured,
                    in_project_scope=(engine in in_scope_asr) if project_id else None,
                )
                for engine in asr_allowed if engine in SERVER_ASR_PROVIDERS
            ],
            stream=[
                ServerAsrCapability(
                    id=engine,
                    configured=engine in stream_configured,
                    in_project_scope=(engine in in_scope_asr) if project_id else None,
                )
                for engine in asr_allowed if engine in STREAM_ASR_PROVIDERS
            ],
            browser=[
                BrowserAsrCapability(
                    id=BROWSER_ASR_PROVIDER,
                    in_project_scope=(BROWSER_ASR_PROVIDER in in_scope_asr) if project_id else None,
                )
                for engine in asr_allowed if engine == BROWSER_ASR_PROVIDER
            ],
        ),
    )
    payload = capabilities.model_dump(mode="json")
    if not project_id:
        for group in ("batch", "stream", "browser"):
            for item in payload["asr"][group]:
                item.pop("in_project_scope", None)

    if policy is None:
        payload.pop("project_policy")
        return JSONResponse(content=payload)
    payload["project_policy"] = ProjectPolicyCapability(
        project_id=project_id,
        allowed_asr_engines=list(policy.allowed_asr_engines),
        default_asr_engine=policy.default_asr_engine,
        taiwanese_asr_engine=policy.taiwanese_asr_engine,
        allowed_tts_voices=list(policy.allowed_tts_voices),
        default_tts_voice=policy.default_tts_voice,
        effective_tts_voice=_effective_voice(current, runtime, project_id),
        allowed_characters=list(policy.allowed_characters),
        default_character_id=policy.default_character_id,
        allowed_backgrounds=list(policy.allowed_backgrounds),
        default_background_id=policy.default_background_id,
        allowed_mascots=list(policy.allowed_mascots),
        default_mascot_id=policy.default_mascot_id,
    ).model_dump(mode="json")
    return JSONResponse(content=payload)


def _effective_voice(
    current: CurrentAccount,
    runtime: AuthRuntime,
    project_id: str,
) -> str:
    try:
        authorized = resolve_tts_voice(
            current, runtime,
            requested_provider="", requested_voice="", project_id=project_id,
        )
    except HTTPException:
        # 專案限制與帳號授權沒有交集：沒有能用的聲音。
        return ""
    return authorized.resource_id if authorized else ""

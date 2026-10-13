"""Discover the caller's resources using the existing scoped list endpoints."""

from __future__ import annotations

import json
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app import project_routes
from app.auth.dependencies import CurrentAccount, get_current_account
from app.auth.runtime import AuthRuntime, get_auth_runtime
from app.auth.settings_repository import (
    BROWSER_ASR_PROVIDER,
    SERVER_ASR_PROVIDERS,
    STREAM_ASR_PROVIDERS,
)
from app.auth.settings_routes import get_my_asr_provider
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


class BrowserAsrCapability(BaseModel):
    id: str
    configured: None = None


class AsrCapabilities(BaseModel):
    value: str
    effective: str
    allowed: list[str]
    batch: list[ServerAsrCapability]
    stream: list[ServerAsrCapability]
    browser: list[BrowserAsrCapability]


class TtsCapabilities(BaseModel):
    providers: list[dict[str, Any]]


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


@router.get(
    "/api/v1/me/capabilities",
    response_model=AccountCapabilities,
    responses={
        403: {"description": "不接受 Embed key"},
        502: {"description": "專案服務回應失敗或格式無效"},
        503: {"description": "專案服務暫時無法連線"},
    },
    summary="取得目前帳號的串接能力與授權資源",
)
async def get_capabilities(
    request: Request,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AccountCapabilities:
    if current.embed_key is not None:
        # Embed keys bind a narrower set than their owner's account grants.
        raise HTTPException(
            status_code=403,
            detail="Account capabilities are unavailable to embed keys",
        )

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

    characters = await avatar.list_characters(current, runtime)
    mascot_list = await mascots.list_mascots(current, runtime)
    background_list = await backgrounds.list_backgrounds(current, runtime)
    tts_providers = await admin.get_tts_providers(current, runtime)
    asr = get_my_asr_provider(current, runtime)
    batch_configured = set(configured_providers())
    stream_configured = set(configured_stream_engines())
    defaults = runtime.account_access.get_defaults(current.user.id)

    return AccountCapabilities(
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
            effective=asr.effective,
            allowed=asr.allowed,
            batch=[
                ServerAsrCapability(
                    id=engine, configured=engine in batch_configured,
                )
                for engine in asr.allowed if engine in SERVER_ASR_PROVIDERS
            ],
            stream=[
                ServerAsrCapability(
                    id=engine, configured=engine in stream_configured,
                )
                for engine in asr.allowed if engine in STREAM_ASR_PROVIDERS
            ],
            browser=[
                BrowserAsrCapability(id=BROWSER_ASR_PROVIDER)
                for engine in asr.allowed if engine == BROWSER_ASR_PROVIDER
            ],
        ),
    )

"""Admin and internal runtime configuration for typed decision providers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .decision_provider_repository import (
    DECISION_CREDENTIAL_IDS,
    DECISION_HOPS,
    DEFAULT_DECISION_ORDER,
    DecisionProviderSettings,
    InvalidDecisionProviderSettings,
)
from .dependencies import CurrentAccount, require_admin
from .runtime import AuthRuntime, get_auth_runtime

router = APIRouter(prefix="/api/v1/settings/decision-providers", tags=["Settings"])


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UpdateDecisionProviderSettings(_StrictModel):
    order: list[str] = Field(min_length=len(DEFAULT_DECISION_ORDER), max_length=len(DEFAULT_DECISION_ORDER))
    enabled: list[str] = Field(max_length=len(DEFAULT_DECISION_ORDER))
    credentials: dict[str, str] = Field(default_factory=dict)
    clear_credentials: list[str] = Field(default_factory=list)
    use_environment_credentials: list[str] = Field(default_factory=list)


def _environment_credential(runtime: AuthRuntime, provider_id: str) -> str:
    if provider_id == "clef":
        return runtime.config.clef_api_key
    if provider_id == "jev":
        return runtime.config.typesafe_api_key
    if provider_id == "openai":
        return runtime.config.decision_openai_api_key
    raise InvalidDecisionProviderSettings("unknown decision provider credential")


def _endpoint(runtime: AuthRuntime, hop_id: str) -> str:
    if hop_id == "jev":
        base = runtime.config.jev_base_url.strip().rstrip("/") or "https://api.typesafe.ai"
        return base if base.endswith("/v1/systemone") else f"{base}/v1/systemone"
    return str(DECISION_HOPS[hop_id]["endpoint"])


def _provider_status(runtime: AuthRuntime) -> dict[str, Any]:
    settings = runtime.decision_providers.get_settings()
    providers = []
    for hop_id in settings.order:
        hop = DECISION_HOPS[hop_id]
        credential_id = str(hop["credential_id"])
        credential = runtime.decision_providers.get_credential_status(
            credential_id,
            env_default=_environment_credential(runtime, credential_id),
        )
        providers.append({
            "id": hop_id,
            "provider": hop["provider"],
            "label": hop["label"],
            "endpoint": _endpoint(runtime, hop_id),
            "model": hop["model"],
            "enabled": hop_id in settings.enabled,
            "credential_required": hop["required"],
            "credential_configured": credential.configured,
            "credential_source": credential.source,
            "credential_masked": credential.masked,
        })
    return {"order": list(settings.order), "enabled": list(settings.enabled), "providers": providers}


@router.get("")
def get_decision_provider_settings(
    _actor: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, Any]:
    return _provider_status(runtime)


@router.put("")
def update_decision_provider_settings(
    body: UpdateDecisionProviderSettings,
    actor: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, Any]:
    reset_credentials = set(body.use_environment_credentials)
    unknown_credentials = (
        set(body.credentials) | set(body.clear_credentials) | reset_credentials
    ) - DECISION_CREDENTIAL_IDS
    if unknown_credentials:
        raise HTTPException(status_code=422, detail="unknown decision credential provider")
    actions = (set(body.credentials), set(body.clear_credentials), reset_credentials)
    if actions[0] & actions[1] or actions[0] & actions[2] or actions[1] & actions[2]:
        raise HTTPException(status_code=422, detail="credential has conflicting update actions")
    credentials = dict(body.credentials)
    credentials.update({provider_id: "" for provider_id in body.clear_credentials})
    try:
        runtime.decision_providers.update(
            body.order,
            body.enabled,
            credentials=credentials,
            reset_credentials=body.use_environment_credentials,
            actor_id=actor.user.id,
        )
    except InvalidDecisionProviderSettings as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="decision credential encryption is unavailable") from exc
    return _provider_status(runtime)


def internal_runtime_configuration(runtime: AuthRuntime) -> dict[str, Any]:
    settings: DecisionProviderSettings = runtime.decision_providers.get_settings()
    providers = []
    for hop_id in settings.order:
        if hop_id not in settings.enabled:
            continue
        hop = DECISION_HOPS[hop_id]
        credential_id = str(hop["credential_id"])
        providers.append({
            "id": hop_id,
            "provider": hop["provider"],
            "endpoint": _endpoint(runtime, hop_id),
            "model": hop["model"],
            "api_key": runtime.decision_providers.get_credential(
                credential_id,
                env_default=_environment_credential(runtime, credential_id),
            ),
            "credential_required": bool(hop["required"]),
        })
    return {"order": [provider["id"] for provider in providers], "providers": providers}


__all__ = ["internal_runtime_configuration", "router"]

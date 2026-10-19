"""ROOT-only model provider settings and the runtime view Brain polls."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .dependencies import CurrentAccount, require_root
from .model_provider_catalog import (
    CATEGORIES,
    CHAT_LLM,
    CREDENTIAL_IDS,
    CREDENTIALS,
    DECISION,
    ModelCategory,
    category_defaults,
    environment_credential,
    hop_endpoint,
)
from .model_provider_repository import (
    CategorySettings,
    CategoryUpdate,
    InvalidModelProviderSettings,
)
from .project_gemini_credentials import GeminiCredential, resolve_gemini_credential
from .runtime import AuthRuntime, get_auth_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings/model-providers", tags=["Settings"])

_HEALTH_TIMEOUT_SECONDS = 1.5
_STATUS_SEVERITY = {"degraded": 1, "cooling": 2, "blocked": 3}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategoryChange(_StrictModel):
    order: list[str] = Field(max_length=16)
    enabled: list[str] = Field(max_length=16)
    # 空字串＝改回部署預設。
    models: dict[str, str] = Field(default_factory=dict)


class UpdateModelProviderSettings(_StrictModel):
    # 只送有改的類別：沒改的類別維持部署設定，第一次只存決策時主對話不會被一起改走。
    categories: dict[str, CategoryChange] = Field(default_factory=dict)
    # 刪掉這些類別的後台設定，回到照部署設定運作。
    reset_categories: list[str] = Field(default_factory=list)
    credentials: dict[str, str] = Field(default_factory=dict)
    clear_credentials: list[str] = Field(default_factory=list)
    use_environment_credentials: list[str] = Field(default_factory=list)


def _effective(runtime: AuthRuntime, category: ModelCategory) -> tuple[CategorySettings, bool]:
    saved = runtime.model_providers.get_settings(category.id)
    defaults = category_defaults(runtime.config, category)
    if saved is None:
        return CategorySettings(defaults.order, defaults.enabled), False
    return saved, True


def _model(runtime: AuthRuntime, category: ModelCategory, settings: CategorySettings, hop_id: str) -> str:
    return settings.models.get(hop_id) or category_defaults(runtime.config, category).models.get(
        hop_id, category.hop(hop_id).model,
    )


def _credential_value(runtime: AuthRuntime, credential_id: str) -> str:
    return runtime.model_providers.get_credential(
        credential_id, env_default=environment_credential(runtime.config, credential_id),
    )


class ResetProviderHealth(_StrictModel):
    category: str | None = Field(default=None, max_length=32)
    hop: str | None = Field(default=None, max_length=64)


def _brain_post(runtime: AuthRuntime, path: str, body: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Best-effort internal call to Brain; None when Brain cannot be reached."""
    config = runtime.config
    try:
        response = httpx.post(
            f"{config.brain_url.rstrip('/')}{path}",
            json=body or {},
            headers={"X-Internal-Token": config.gateway_internal_token},
            timeout=_HEALTH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        result = response.json()
    except Exception as exc:  # noqa: BLE001 - Brain 暫時連不上時設定照常存，10 秒內自己會讀到
        logger.warning("Brain internal call %s failed: %s", path, exc)
        return None
    return result if isinstance(result, dict) else {}


def _key_fingerprint(api_key: str) -> str:
    # 與 Brain core/provider_health.key_fingerprint 相同算法，用來對上「這把 key」的失敗紀錄。
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


def _brain_provider_health(runtime: AuthRuntime) -> list[dict[str, Any]] | None:
    """Hops Brain is currently skipping or cooling, or None when Brain can't be asked."""
    config = runtime.config
    try:
        response = httpx.get(
            f"{config.brain_url.rstrip('/')}/brain/internal/provider-health",
            headers={"X-Internal-Token": config.gateway_internal_token},
            timeout=_HEALTH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        hops = response.json().get("hops")
    except Exception as exc:  # noqa: BLE001 - 狀態查不到不能讓設定頁打不開
        logger.warning("provider health unavailable from Brain: %s", exc)
        return None
    return hops if isinstance(hops, list) else None


def _hop_health(
    health: list[dict[str, Any]] | None,
    *,
    category: str,
    hop_id: str,
    model: str,
    api_key: str,
) -> dict[str, Any]:
    if health is None:
        return {"status": "unknown"}
    fingerprint = _key_fingerprint(api_key)
    matches = [
        entry for entry in health
        if isinstance(entry, dict)
        and entry.get("category") == category
        and entry.get("hop") == hop_id
        and entry.get("model") == model
        and entry.get("key_fingerprint") == fingerprint
    ]
    if not matches:
        return {"status": "ok"}
    # Brain 依用途（每輪決策、附圖選擇…）分開記；頁面一站只顯示一個狀態，取最嚴重的那個。
    worst = max(matches, key=lambda entry: _STATUS_SEVERITY.get(str(entry.get("status")), 0))
    reason = str(worst.get("reason", ""))
    if worst.get("purpose"):
        reason = f"{reason}（{worst['purpose']}）" if reason else str(worst["purpose"])
    return {
        "status": worst.get("status", "unknown"),
        "reason": reason,
        "retry_in_seconds": worst.get("retry_in_seconds"),
    }


def _admin_view(runtime: AuthRuntime) -> dict[str, Any]:
    health = _brain_provider_health(runtime)
    credentials = []
    for credential in CREDENTIALS:
        status = runtime.model_providers.get_credential_status(
            credential.id,
            env_default=environment_credential(runtime.config, credential.id),
        )
        users = [
            category for category in CATEGORIES.values()
            if any(hop.credential_id == credential.id for hop in category.hops)
        ]
        credentials.append({
            "id": credential.id,
            "label": credential.label,
            "environment_variable": credential.environment_variable,
            "used_by": [category.label for category in users],
            "required": any(
                hop.credential_required
                for category in users for hop in category.hops
                if hop.credential_id == credential.id
            ),
            "configured": status.configured,
            "source": status.source,
            "masked": status.masked,
        })
    categories = []
    for category in CATEGORIES.values():
        settings, configured = _effective(runtime, category)
        defaults = category_defaults(runtime.config, category)
        providers = []
        for hop_id in settings.order:
            hop = category.hop(hop_id)
            model = _model(runtime, category, settings, hop.id)
            providers.append({
                "id": hop.id,
                "credential_id": hop.credential_id,
                "label": hop.label,
                "endpoint": hop_endpoint(runtime.config, category, hop),
                "model": model,
                "health": _hop_health(
                    health,
                    category=category.id,
                    hop_id=hop.id,
                    model=model,
                    api_key=_credential_value(runtime, hop.credential_id),
                ),
                "default_model": defaults.models.get(hop.id, hop.model),
                "model_override": settings.models.get(hop.id, ""),
                "enabled": hop.id in settings.enabled,
                "credential_required": hop.credential_required,
            })
        categories.append({
            "id": category.id,
            "label": category.label,
            "model_editable": category.model_editable,
            "configured": configured,
            "order": list(settings.order),
            "enabled": list(settings.enabled),
            "providers": providers,
        })
    return {"credentials": credentials, "categories": categories}


@router.get("")
def get_model_provider_settings(
    _actor: CurrentAccount = Depends(require_root),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, Any]:
    return _admin_view(runtime)


@router.put("")
def update_model_provider_settings(
    body: UpdateModelProviderSettings,
    actor: CurrentAccount = Depends(require_root),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, Any]:
    if not set(body.categories) | set(body.reset_categories) <= set(CATEGORIES):
        raise HTTPException(status_code=422, detail="unknown model category")
    if set(body.categories) & set(body.reset_categories):
        raise HTTPException(status_code=422, detail="category cannot be saved and reset together")
    reset_credentials = set(body.use_environment_credentials)
    unknown_credentials = (
        set(body.credentials) | set(body.clear_credentials) | reset_credentials
    ) - CREDENTIAL_IDS
    if unknown_credentials:
        raise HTTPException(status_code=422, detail="unknown model provider credential")
    actions = (set(body.credentials), set(body.clear_credentials), reset_credentials)
    if actions[0] & actions[1] or actions[0] & actions[2] or actions[1] & actions[2]:
        raise HTTPException(status_code=422, detail="credential has conflicting update actions")
    credentials = dict(body.credentials)
    credentials.update({credential_id: "" for credential_id in body.clear_credentials})
    changes = {
        category_id: CategoryUpdate(
            tuple(change.order),
            tuple(change.enabled),
            {hop_id: model.strip() for hop_id, model in change.models.items() if model.strip()},
        )
        for category_id, change in body.categories.items()
    }
    try:
        runtime.model_providers.update(
            changes,
            reset_categories=body.reset_categories,
            credentials=credentials,
            reset_credentials=body.use_environment_credentials,
            actor_id=actor.user.id,
        )
    except InvalidModelProviderSettings as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="model credential encryption is unavailable") from exc
    # Brain 每 10 秒才重讀一次設定；存完主動叫它清快取，改完馬上到前台測就看得到。
    refreshed = _brain_post(runtime, "/brain/internal/model-providers/refresh") is not None
    return {**_admin_view(runtime), "runtime_refreshed": refreshed}


@router.post("/health/reset")
def reset_model_provider_health(
    body: ResetProviderHealth,
    _actor: CurrentAccount = Depends(require_root),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, Any]:
    if body.category is not None and body.category not in CATEGORIES:
        raise HTTPException(status_code=422, detail="unknown model category")
    result = _brain_post(
        runtime, "/brain/internal/provider-health/reset",
        {"category": body.category, "hop": body.hop},
    )
    if result is None:
        raise HTTPException(status_code=503, detail="Brain is unavailable; provider health was not reset")
    return _admin_view(runtime)


def _decision_runtime(runtime: AuthRuntime) -> dict[str, Any]:
    settings, _ = _effective(runtime, DECISION)
    providers = []
    for hop_id in settings.order:
        if hop_id not in settings.enabled:
            continue
        hop = DECISION.hop(hop_id)
        providers.append({
            "id": hop.id,
            "provider": hop.credential_id,
            "endpoint": hop_endpoint(runtime.config, DECISION, hop),
            "model": hop.model,
            "api_key": _credential_value(runtime, hop.credential_id),
            "credential_required": hop.credential_required,
        })
    return {"order": [provider["id"] for provider in providers], "providers": providers}


def _chat_llm_runtime(
    runtime: AuthRuntime, gemini: GeminiCredential,
) -> dict[str, Any]:
    settings, configured = _effective(runtime, CHAT_LLM)
    # 沒人存過就讓 Brain 照自己的 LLM_FALLBACK_CHAIN 跑，部署後行為完全不變。
    # 但金鑰是各類共用的：後台存過（含刻意清除）的 key 仍要蓋過 Brain 的 .env，
    # 不然改了 OpenAI key，決策用新的、主對話還在用舊的。
    if not configured:
        overrides: dict[str, str] = {}
        for credential_id in {hop.credential_id for hop in CHAT_LLM.hops}:
            status = runtime.model_providers.get_credential_status(
                credential_id,
                env_default=environment_credential(runtime.config, credential_id),
            )
            if status.source == "admin":
                overrides[credential_id] = _credential_value(runtime, credential_id)
        if gemini.source == "project":
            overrides["gemini"] = gemini.api_key
        return {"configured": False, "credential_overrides": overrides}
    providers = []
    for hop_id in settings.order:
        if hop_id not in settings.enabled:
            continue
        hop = CHAT_LLM.hop(hop_id)
        status = runtime.model_providers.get_credential_status(
            hop.credential_id,
            env_default=environment_credential(runtime.config, hop.credential_id),
        )
        providers.append({
            "id": hop.id,
            "provider": hop.credential_id,
            "endpoint": hop_endpoint(runtime.config, CHAT_LLM, hop),
            "model": _model(runtime, CHAT_LLM, settings, hop.id),
            "api_key": (
                gemini.api_key if hop.credential_id == "gemini"
                else _credential_value(runtime, hop.credential_id)
            ),
            "credential_source": (
                "project"
                if hop.credential_id == "gemini" and gemini.source == "project"
                else status.source
            ),
        })
    result = {
        "configured": True,
        "order": [provider["id"] for provider in providers],
        "providers": providers,
    }
    if gemini.source == "project":
        result["credential_overrides"] = {"gemini": gemini.api_key}
    return result


def internal_runtime_configuration(
    runtime: AuthRuntime, project_id: str | None = None,
) -> dict[str, Any]:
    gemini = resolve_gemini_credential(project_id, runtime)
    return {
        "decision": _decision_runtime(runtime),
        "chat_llm": _chat_llm_runtime(runtime, gemini),
        "gemini_credential": {
            "api_key": gemini.api_key,
            "source": gemini.source,
            "credential_id": gemini.credential_id,
            "configured": gemini.configured,
        },
    }


__all__ = ["internal_runtime_configuration", "router"]

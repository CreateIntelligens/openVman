"""Bounded fallback chain for LLM provider/model routing."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

from config import get_settings
from core.gemini_credentials import (
    clear_project_provider_cache,
    current_model_project,
    project_provider_document,
    resolve_gemini_credential,
)
from core.model_provider_config import RefreshingValue, fetch_section
from core.provider_health import HopId, provider_health
from safety.observability import log_event

logger = logging.getLogger("core.fallback_chain")

_ADMIN_PROVIDERS: Final = frozenset({"gemini", "openai", "groq", "nen"})
# 本機 Backend 正常是毫秒級回應；設上限是怕 Backend 卡住時拖慢每 10 秒那一輪對話。
_ADMIN_CONFIG_TIMEOUT_SECONDS: Final = 1.0


@dataclass(frozen=True, slots=True)
class _ChainEntry:
    provider: str
    model: str
    api_key: str
    base_url: str


@dataclass(frozen=True, slots=True)
class _AdminChat:
    # None：ROOT 還沒存過主對話設定，鏈照 LLM_FALLBACK_CHAIN。
    chain: tuple[_ChainEntry, ...] | None
    # 後台存過的 key（含刻意清成空字串），蓋過 .env 裡同一家的 key。
    key_overrides: dict[str, str]


_NO_ADMIN_CHAT: Final = _AdminChat(None, {})
_ADMIN_CHAT: RefreshingValue[_AdminChat] = RefreshingValue()


@dataclass(frozen=True, slots=True)
class RouteHop:
    """A single hop in the fallback chain."""

    provider: str
    model: str
    api_key: str
    base_url: str
    hop_index: int
    trace_id: str
    credential_source: str = ""
    credential_id: str = ""


def build_fallback_chain(trace_id: str, client: Any | None = None) -> list[RouteHop]:
    """Build an ordered list of route hops from the configured fallback chain.

    Each (provider, model) pair in the chain gets one hop entry.
    If the provider is 'gemini', it expands to a list of models dynamically
    retrieved from the client/discovery if available, or static fallback models.
    The chain is bounded by ``llm_max_fallback_hops``.

    The Admin's model provider settings win once someone has saved them;
    until then (or while Backend has never answered) LLM_FALLBACK_CHAIN rules.
    """
    cfg = get_settings()
    project_id = current_model_project()
    admin = _admin_chat()
    credential = resolve_gemini_credential(project_id) if project_id is not None else None
    entries = list(admin.chain) if admin.chain is not None else _environment_chain(admin.key_overrides)
    source = "admin" if admin.chain is not None else "environment"
    # 一把可用 key 都沒有（全停用、金鑰全清掉）時，照 .env 原樣跑，
    # 不讓一次設定失誤讓整個聊天停擺。
    if not any(entry.api_key for entry in entries):
        if admin.chain is not None or admin.key_overrides:
            logger.warning("admin chat provider settings leave no usable key; using environment chain")
        entries = _environment_chain({})
        source = "environment"

    if credential is not None:
        entries = [
            _ChainEntry(entry.provider, entry.model,
                        credential.api_key if entry.provider == "gemini" else entry.api_key,
                        entry.base_url)
            for entry in entries
        ]

    from core.models_config import fallback_chain

    # Expand the chain_spec if there are gemini models. When model discovery is
    # disabled, the chain is used exactly as configured (no auto-expansion of
    # every available Gemini model into the chain).
    expanded: list[_ChainEntry] = []
    for entry in entries:
        if entry.provider == "gemini" and not cfg.llm_disable_model_discovery:
            for model in fallback_chain(entry.model, client=client):
                expanded.append(_ChainEntry(entry.provider, model, entry.api_key, entry.base_url))
        else:
            expanded.append(entry)

    hops: list[RouteHop] = []
    for entry in provider_health().order(expanded, _entry_health_id):
        if len(hops) >= cfg.llm_max_fallback_hops:
            break
        if not entry.api_key:
            continue
        hops.append(
            RouteHop(
                provider=entry.provider,
                model=entry.model,
                api_key=entry.api_key,
                base_url=entry.base_url,
                hop_index=len(hops),
                trace_id=trace_id,
                credential_source=credential.source if credential and entry.provider == "gemini" else "",
                credential_id=credential.credential_id if credential and entry.provider == "gemini" else "",
            )
        )

    log_event(
        "fallback_chain_built",
        trace_id=trace_id,
        hops=len(hops),
        source=source,
        chain=[f"{h.provider}:{h.model}" for h in hops],
    )
    return hops


def health_id(provider: str, model: str, api_key: str) -> HopId:
    return HopId.of("chat_llm", provider, model, api_key)


def _entry_health_id(entry: _ChainEntry) -> HopId:
    return health_id(entry.provider, entry.model, entry.api_key)


def _environment_chain(key_overrides: dict[str, str]) -> list[_ChainEntry]:
    cfg = get_settings()
    return [
        _ChainEntry(
            provider,
            model,
            key_overrides.get(provider, cfg.resolve_api_key_for_provider(provider)),
            cfg.resolve_base_url_for_provider(provider),
        )
        for provider, model in cfg.resolved_fallback_chain
    ]


def has_admin_api_key() -> bool:
    """Whether the Admin supplies at least one usable chat key."""
    admin = _admin_chat()
    keys = [entry.api_key for entry in admin.chain or ()] + list(admin.key_overrides.values())
    return any(keys)


def _admin_chat() -> _AdminChat:
    project_id = current_model_project()
    if project_id is not None:
        return _parse_admin_chat(project_provider_document(project_id)["chat_llm"])
    return _ADMIN_CHAT.get(_fetch_admin_chat, default=_NO_ADMIN_CHAT)


def _fetch_admin_chat() -> _AdminChat:
    try:
        section = fetch_section("chat_llm", timeout=_ADMIN_CONFIG_TIMEOUT_SECONDS)
        return _parse_admin_chat(section)
    except Exception as exc:
        logger.warning("chat model provider settings unavailable: %s", exc)
        raise


def _parse_admin_chat(section: Any) -> _AdminChat:
    if not isinstance(section, dict):
        raise ValueError("chat_llm section must be an object")
    if section.get("configured") is not True:
        overrides = section.get("credential_overrides", {})
        if not isinstance(overrides, dict) or not all(
            provider in _ADMIN_PROVIDERS and isinstance(key, str)
            for provider, key in overrides.items()
        ):
            raise ValueError("chat_llm credential overrides are invalid")
        return _AdminChat(None, dict(overrides))
    raw_providers = section.get("providers")
    if not isinstance(raw_providers, list):
        raise ValueError("chat_llm providers must be a list")
    cfg = get_settings()
    entries: list[_ChainEntry] = []
    for raw in raw_providers:
        if not isinstance(raw, dict):
            raise ValueError("chat_llm provider must be an object")
        provider, model = raw.get("provider"), raw.get("model")
        endpoint, api_key = raw.get("endpoint"), raw.get("api_key")
        if (
            provider not in _ADMIN_PROVIDERS
            or not isinstance(model, str) or not model
            or not isinstance(endpoint, str)
            or not isinstance(api_key, str)
        ):
            raise ValueError("chat_llm provider entry is invalid")
        # Backend 看不到金鑰、但 Brain 自己的部署設定有時（兩邊 .env 分開放），
        # 用 Brain 的；後台明確清除的金鑰（source=admin）不補，該供應商就略過。
        if not api_key and raw.get("credential_source") not in {"admin", "project"}:
            api_key = cfg.resolve_api_key_for_provider(provider)
        entries.append(_ChainEntry(provider, model, api_key, endpoint))
    return _AdminChat(tuple(entries), {})


def clear_admin_chain_cache() -> None:
    _ADMIN_CHAT.clear()
    clear_project_provider_cache()


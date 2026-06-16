"""Bounded fallback chain for LLM provider/model routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import get_settings
from safety.observability import log_event


@dataclass(frozen=True, slots=True)
class RouteHop:
    """A single hop in the fallback chain."""

    provider: str
    model: str
    api_key: str
    base_url: str
    hop_index: int
    trace_id: str


def build_fallback_chain(trace_id: str, client: Any | None = None) -> list[RouteHop]:
    """Build an ordered list of route hops from the configured fallback chain.

    Each (provider, model) pair in the chain gets one hop entry.
    If the provider is 'gemini', it expands to a list of models dynamically
    retrieved from the client/discovery if available, or static fallback models.
    The chain is bounded by ``llm_max_fallback_hops``.
    """
    cfg = get_settings()
    chain_spec = cfg.resolved_fallback_chain
    max_hops = cfg.llm_max_fallback_hops

    from core.models_config import fallback_chain

    # Expand the chain_spec if there are gemini models. When model discovery is
    # disabled, the chain is used exactly as configured (no auto-expansion of
    # every available Gemini model into the chain).
    expanded_spec: list[tuple[str, str]] = []
    for provider, model in chain_spec:
        if provider == "gemini" and not cfg.llm_disable_model_discovery:
            gemini_models = fallback_chain(model, client=client)
            for m in gemini_models:
                expanded_spec.append((provider, m))
        else:
            expanded_spec.append((provider, model))

    hops: list[RouteHop] = []
    hop_idx = 0
    for provider, model in expanded_spec:
        if hop_idx >= max_hops:
            break
        api_key = cfg.resolve_api_key_for_provider(provider)
        if not api_key:
            continue
        hops.append(
            RouteHop(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=cfg.resolve_base_url_for_provider(provider),
                hop_index=hop_idx,
                trace_id=trace_id,
            )
        )
        hop_idx += 1

    log_event(
        "fallback_chain_built",
        trace_id=trace_id,
        hops=len(hops),
        chain=[f"{h.provider}:{h.model}" for h in hops],
    )
    return hops


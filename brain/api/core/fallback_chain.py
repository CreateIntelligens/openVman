"""Bounded fallback chain for LLM provider/model routing."""

from __future__ import annotations

from dataclasses import dataclass

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


def build_fallback_chain(trace_id: str) -> list[RouteHop]:
    """Build an ordered list of route hops from the configured fallback chain.

    Each (provider, model) pair in the chain gets one hop entry.
    The chain is bounded by ``llm_max_fallback_hops``.
    """
    cfg = get_settings()
    chain_spec = cfg.resolved_fallback_chain
    max_hops = cfg.llm_max_fallback_hops

    hops: list[RouteHop] = []
    for idx, (provider, model) in enumerate(chain_spec):
        if idx >= max_hops:
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
                hop_index=idx,
                trace_id=trace_id,
            )
        )

    log_event(
        "fallback_chain_built",
        trace_id=trace_id,
        hops=len(hops),
        chain=[f"{h.provider}:{h.model}" for h in hops],
    )
    return hops

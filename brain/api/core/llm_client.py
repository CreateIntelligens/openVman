"""LLM client wrapper with bounded fallback chain execution."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from time import monotonic
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI, OpenAI

from config import get_settings
from core.fallback_chain import RouteHop, build_fallback_chain
from core.key_pool import classify_failure
from core.provider_router import LLMRoute, get_provider_router
from privacy.filter import FilterSource, sanitize_llm_messages, sanitize_llm_reply_text
from safety.observability import (
    log_event,
    record_chain_exhausted,
    record_fallback_hop,
    record_route_attempt,
)


def _require_api_key() -> None:
    """Raise early if the LLM API key is not configured."""
    if not get_settings().resolved_llm_api_keys:
        raise ValueError("BRAIN_LLM_API_KEY / BRAIN_LLM_API_KEYS 尚未設定")


@dataclass(frozen=True, slots=True)
class LLMToolCall:
    id: str
    name: str
    arguments: str
    extra_content: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class LLMReply:
    content: str
    tool_calls: list[LLMToolCall]
    model: str


def generate_chat_reply(
    messages: list[dict[str, Any]],
    *,
    model_override: str | None = None,
    trace_id: str = "",
    privacy_source: FilterSource = "unknown",
) -> str:
    """Generate a chat reply using the configured provider."""
    reply = generate_chat_turn(
        messages,
        model_override=model_override,
        trace_id=trace_id,
        privacy_source=privacy_source,
    ).content.strip()
    return sanitize_llm_reply_text(reply)


def generate_chat_turn(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    trace_id: str = "",
    model_override: str | None = None,
    privacy_source: FilterSource = "unknown",
) -> LLMReply:
    """Request one non-stream chat completion turn with fallback chain."""
    sanitized_messages = sanitize_llm_messages(
        messages,
        source=privacy_source,
        trace_id=trace_id,
    )
    response = _create_sync_completion(
        sanitized_messages,
        tools=tools,
        trace_id=trace_id,
        model_override=model_override,
    )
    message = response.choices[0].message
    content = (message.content or "").strip()
    tool_calls = [
        LLMToolCall(
            id=tool_call.id,
            name=tool_call.function.name,
            arguments=tool_call.function.arguments,
            extra_content=_extract_tool_call_extra_content(tool_call),
        )
        for tool_call in (message.tool_calls or [])
    ]
    if not content and not tool_calls:
        raise ValueError("LLM 沒有回傳內容")
    return LLMReply(
        content=content,
        tool_calls=tool_calls,
        model=response.model,
    )


async def stream_chat_reply(
    messages: list[dict[str, Any]],
    *,
    trace_id: str = "",
    privacy_source: FilterSource = "unknown",
) -> AsyncIterator[str]:
    """Stream a chat reply token-by-token with fallback chain."""
    sanitized_messages = sanitize_llm_messages(
        messages,
        source=privacy_source,
        trace_id=trace_id,
    )
    stream = await _create_async_stream(sanitized_messages, trace_id=trace_id, tool_choice="none")

    tokens: list[str] = []
    async for chunk in stream:
        if not chunk.choices:
            continue
        token = chunk.choices[0].delta.content or ""
        if token:
            tokens.append(token)

    yield sanitize_llm_reply_text("".join(tokens))


# ---------------------------------------------------------------------------
# Shared chain resolution
# ---------------------------------------------------------------------------

def _resolve_chain_or_routes(
    trace_id: str,
) -> tuple[list[RouteHop], list[LLMRoute]]:
    """Resolve the fallback chain; fall back to legacy routes if empty.

    Returns (chain, legacy_routes) where exactly one list is non-empty.
    Raises RuntimeError if neither source has available routes.
    """
    chain = build_fallback_chain(trace_id)
    if chain:
        return chain, []

    routes = get_provider_router().iter_routes()
    if not routes:
        raise RuntimeError("無可用的 LLM route")
    return [], routes


def _record_hop_failure(
    hop: RouteHop,
    exc: Exception,
    latency_ms: float,
    chain: list[RouteHop],
    errors: list[str],
    trace_id: str,
) -> str:
    """Shared failure handling for a single hop. Returns the failure reason."""
    reason = classify_failure(exc)
    router = get_provider_router()
    router.mark_failure(hop.api_key, hop.model, exc)

    record_route_attempt(
        trace_id=trace_id,
        provider=hop.provider,
        model=hop.model,
        hop_index=hop.hop_index,
        result="failure",
        latency_ms=latency_ms,
        reason=reason,
        chain_length=len(chain),
    )
    errors.append(
        f"hop{hop.hop_index} {hop.provider}:{hop.model}: "
        f"{type(exc).__name__}: {exc}"
    )

    next_idx = hop.hop_index + 1
    if next_idx < len(chain):
        next_hop = chain[next_idx]
        record_fallback_hop(
            trace_id=trace_id,
            from_provider=hop.provider,
            from_model=hop.model,
            to_provider=next_hop.provider,
            to_model=next_hop.model,
            reason=reason,
            hop_index=next_idx,
        )

    return reason


def _raise_chain_exhausted(
    trace_id: str, errors: list[str], last_reason: str, hop_count: int
) -> None:
    """Record exhaustion and raise a RuntimeError."""
    record_chain_exhausted(trace_id=trace_id, final_reason=last_reason, hops=hop_count)
    raise RuntimeError(
        f"所有 fallback chain hops 皆失敗 (trace={trace_id}): " + " | ".join(errors)
    )


# ---------------------------------------------------------------------------
# Sync completion
# ---------------------------------------------------------------------------

def _create_sync_completion(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    trace_id: str = "",
    model_override: str | None = None,
):
    _require_api_key()
    cfg = get_settings()
    router = get_provider_router()
    tid = trace_id or uuid.uuid4().hex[:12]

    chain, legacy_routes = _resolve_chain_or_routes(tid)
    chain, legacy_routes = _apply_model_override(
        chain,
        legacy_routes,
        model_override,
    )

    if legacy_routes:
        return _try_routes_sync(legacy_routes, messages, tools, cfg, router)

    errors: list[str] = []
    last_reason = ""

    for hop in chain:
        t0 = _now_ms()
        client = OpenAI(api_key=hop.api_key, base_url=hop.base_url or None)
        try:
            response = client.chat.completions.create(
                model=hop.model,
                messages=messages,
                temperature=cfg.llm_temperature,
                **_build_create_kwargs(tools),
            )
            router.mark_success(hop.api_key)
            record_route_attempt(
                trace_id=tid,
                provider=hop.provider,
                model=hop.model,
                hop_index=hop.hop_index,
                result="success",
                latency_ms=_now_ms() - t0,
                chain_length=len(chain),
            )
            return response
        except Exception as exc:
            last_reason = _record_hop_failure(
                hop, exc, _now_ms() - t0, chain, errors, tid
            )

    _raise_chain_exhausted(tid, errors, last_reason, len(chain))


def _apply_model_override(
    chain: list[RouteHop],
    legacy_routes: list[LLMRoute],
    model_override: str | None,
) -> tuple[list[RouteHop], list[LLMRoute]]:
    """Rewrite resolved routes to a single model when an override is supplied."""
    if not model_override:
        return chain, legacy_routes

    if (
        all(hop.model == model_override for hop in chain)
        and all(route.model == model_override for route in legacy_routes)
    ):
        return chain, legacy_routes

    overridden_chain = [
        RouteHop(
            provider=hop.provider,
            model=model_override,
            api_key=hop.api_key,
            base_url=hop.base_url,
            hop_index=hop.hop_index,
            trace_id=hop.trace_id,
        )
        for hop in chain
    ]
    overridden_legacy_routes = [
        LLMRoute(
            api_key=route.api_key,
            model=model_override,
            base_url=route.base_url,
        )
        for route in legacy_routes
    ]
    return overridden_chain, overridden_legacy_routes


def _try_routes_sync(routes, messages, tools, cfg, router):
    """Legacy route loop for when no fallback chain is configured."""
    errors: list[str] = []
    for route in routes:
        client = OpenAI(api_key=route.api_key, base_url=route.base_url or None)
        try:
            response = client.chat.completions.create(
                model=route.model,
                messages=messages,
                temperature=cfg.llm_temperature,
                **_build_create_kwargs(tools),
            )
            router.mark_success(route.api_key)
            return response
        except Exception as exc:
            router.mark_failure(route.api_key, route.model, exc)
            errors.append(f"{route.model}: {type(exc).__name__}: {exc}")

    raise RuntimeError("所有 LLM route 皆失敗: " + " | ".join(errors))


# ---------------------------------------------------------------------------
# Async streaming
# ---------------------------------------------------------------------------

async def _create_async_stream(
    messages: list[dict[str, Any]],
    *,
    trace_id: str = "",
    tool_choice: str | None = None,
):
    _require_api_key()
    cfg = get_settings()
    router = get_provider_router()
    tid = trace_id or uuid.uuid4().hex[:12]

    chain, legacy_routes = _resolve_chain_or_routes(tid)

    if legacy_routes:
        return await _try_routes_async(legacy_routes, messages, cfg, router, tool_choice=tool_choice)

    errors: list[str] = []
    last_reason = ""

    for hop in chain:
        log_event(
            "fallback_hop_attempt",
            trace_id=tid,
            hop_index=hop.hop_index,
            provider=hop.provider,
            model=hop.model,
        )
        client = AsyncOpenAI(api_key=hop.api_key, base_url=hop.base_url or None)
        try:
            create_kwargs: dict[str, Any] = {"stream": True}
            if tool_choice is not None:
                create_kwargs["tool_choice"] = tool_choice
            stream = await client.chat.completions.create(
                model=hop.model,
                messages=messages,
                temperature=cfg.llm_temperature,
                **create_kwargs,
            )
            router.mark_success(hop.api_key)
            log_event(
                "fallback_hop_success",
                trace_id=tid,
                hop_index=hop.hop_index,
                provider=hop.provider,
                model=hop.model,
            )
            return stream
        except Exception as exc:
            last_reason = _record_hop_failure(
                hop, exc, 0.0, chain, errors, tid
            )

    _raise_chain_exhausted(tid, errors, last_reason, len(chain))


async def _try_routes_async(routes, messages, cfg, router, *, tool_choice: str | None = None):
    """Legacy async route loop."""
    errors: list[str] = []
    extra: dict[str, Any] = {"stream": True}
    if tool_choice is not None:
        extra["tool_choice"] = tool_choice
    for route in routes:
        client = AsyncOpenAI(api_key=route.api_key, base_url=route.base_url or None)
        try:
            stream = await client.chat.completions.create(
                model=route.model,
                messages=messages,
                temperature=cfg.llm_temperature,
                **extra,
            )
            router.mark_success(route.api_key)
            return stream
        except Exception as exc:
            router.mark_failure(route.api_key, route.model, exc)
            errors.append(f"{route.model}: {type(exc).__name__}: {exc}")

    raise RuntimeError("所有 LLM route 皆失敗: " + " | ".join(errors))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_create_kwargs(tools: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not tools:
        return {}
    return {
        "tools": tools,
        "tool_choice": "auto",
    }


def _now_ms() -> float:
    """Return monotonic time in milliseconds."""
    return monotonic() * 1000


def _extract_tool_call_extra_content(tool_call: Any) -> dict[str, Any] | None:
    extra_content = getattr(tool_call, "extra_content", None)
    if extra_content is not None:
        return extra_content

    model_extra = getattr(tool_call, "model_extra", None) or {}
    extra = model_extra.get("extra_content")
    return extra if isinstance(extra, dict) else None

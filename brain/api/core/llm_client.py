"""LLM client wrapper with bounded fallback chain execution."""

from __future__ import annotations

import uuid
from collections import OrderedDict
from time import monotonic
from dataclasses import dataclass
from threading import Lock
from typing import Any, cast

from openai import OpenAI

_CLIENT_CACHE_MAX = 32
_SYNC_CLIENT_CACHE: "OrderedDict[tuple[str, str | None], OpenAI]" = OrderedDict()
_SYNC_CLIENT_CACHE_LOCK = Lock()


def _get_sync_client(api_key: str, base_url: str | None) -> OpenAI:
    key = (api_key, base_url)
    with _SYNC_CLIENT_CACHE_LOCK:
        client = _SYNC_CLIENT_CACHE.get(key)
        if client is not None:
            _SYNC_CLIENT_CACHE.move_to_end(key)
            return client
        client = OpenAI(api_key=api_key, base_url=base_url or None)
        _SYNC_CLIENT_CACHE[key] = client
        if len(_SYNC_CLIENT_CACHE) > _CLIENT_CACHE_MAX:
            _SYNC_CLIENT_CACHE.popitem(last=False)
        return client

from config import get_settings
from core.fallback_chain import RouteHop, build_fallback_chain
from core.key_pool import classify_failure
from core.provider_router import LLMRoute, get_provider_router
from privacy.filter import FilterSource, PiiDetectionReport, detect_llm_messages_pii
from safety.observability import (
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
    pii_report: PiiDetectionReport | None = None



def generate_chat_reply(
    messages: list[dict[str, Any]],
    *,
    model_override: str | None = None,
    trace_id: str = "",
    privacy_source: FilterSource = "unknown",
) -> str:
    """Generate a chat reply using the configured provider."""
    return generate_chat_turn(
        messages,
        model_override=model_override,
        trace_id=trace_id,
        privacy_source=privacy_source,
    ).content.strip()


def generate_chat_turn(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    trace_id: str = "",
    model_override: str | None = None,
    privacy_source: FilterSource = "unknown",
    forced_tool_name: str | None = None,
    max_tokens: int | None = None,
) -> LLMReply:
    """Request one non-stream chat completion turn with fallback chain."""
    pii_report = detect_llm_messages_pii(messages, source=privacy_source, trace_id=trace_id)
    response = _create_sync_completion(
        messages,
        tools=tools,
        trace_id=trace_id,
        model_override=model_override,
        forced_tool_name=forced_tool_name,
        max_tokens=max_tokens,
    )
    assert response is not None
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
        pii_report=pii_report,
    )


def stream_chat_turn(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    trace_id: str = "",
    model_override: str | None = None,
    privacy_source: FilterSource = "unknown",
    forced_tool_name: str | None = None,
    max_tokens: int | None = None,
) -> LLMReply:
    """Stream one chat turn; detect tool calls vs text without a second round-trip.

    Identical return type and signature to generate_chat_turn — callers need no changes.
    Reuses the provider fallback chain and key-pool infrastructure.
    """
    pii_report = detect_llm_messages_pii(messages, source=privacy_source, trace_id=trace_id)
    _require_api_key()
    cfg = get_settings()
    router = get_provider_router()
    tid = trace_id or uuid.uuid4().hex[:12]

    chain, legacy_routes = _resolve_chain_or_routes(tid)
    chain, legacy_routes = _apply_model_override(chain, legacy_routes, model_override)

    create_kwargs = _build_create_kwargs(tools, forced_tool_name=forced_tool_name)
    if max_tokens:
        create_kwargs["max_tokens"] = max_tokens

    if legacy_routes:
        return _stream_routes(legacy_routes, messages, cfg, router, create_kwargs, pii_report=pii_report)

    errors: list[str] = []
    last_reason = ""
    for hop in chain:
        t0 = _now_ms()
        client = _get_sync_client(hop.api_key, hop.base_url)
        try:
            reply = _consume_stream(
                client.chat.completions.create(
                    model=hop.model,
                    messages=cast(Any, messages),
                    temperature=cfg.llm_temperature,
                    stream=True,
                    **create_kwargs,
                ),
                model=hop.model,
                pii_report=pii_report,
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
            return reply
        except ValueError:
            raise
        except Exception as exc:
            last_reason = _record_hop_failure(hop, exc, _now_ms() - t0, chain, errors, tid)

    _raise_chain_exhausted(tid, errors, last_reason, len(chain))


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


def _create_sync_completion(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    trace_id: str = "",
    model_override: str | None = None,
    forced_tool_name: str | None = None,
    max_tokens: int | None = None,
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
        return _try_routes_sync(legacy_routes, messages, tools, cfg, router, forced_tool_name=forced_tool_name, max_tokens=max_tokens)

    errors: list[str] = []
    last_reason = ""

    for hop in chain:
        t0 = _now_ms()
        client = _get_sync_client(hop.api_key, hop.base_url)
        try:
            create_kwargs = _build_create_kwargs(tools, forced_tool_name=forced_tool_name)
            if max_tokens:
                create_kwargs["max_tokens"] = max_tokens
            response = client.chat.completions.create(
                model=hop.model,
                messages=cast(Any, messages),
                temperature=cfg.llm_temperature,
                **create_kwargs,
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


def _try_routes_sync(routes, messages, tools, cfg, router, *, forced_tool_name: str | None = None, max_tokens: int | None = None):
    """Legacy route loop for when no fallback chain is configured."""
    errors: list[str] = []
    for route in routes:
        client = _get_sync_client(route.api_key, route.base_url)
        try:
            create_kwargs = _build_create_kwargs(tools, forced_tool_name=forced_tool_name)
            if max_tokens:
                create_kwargs["max_tokens"] = max_tokens
            response = client.chat.completions.create(
                model=route.model,
                messages=cast(Any, messages),
                temperature=cfg.llm_temperature,
                **create_kwargs,
            )
            router.mark_success(route.api_key)
            return response
        except Exception as exc:
            router.mark_failure(route.api_key, route.model, exc)
            errors.append(f"{route.model}: {type(exc).__name__}: {exc}")

    raise RuntimeError("所有 LLM route 皆失敗: " + " | ".join(errors))


def _consume_stream(stream: Any, *, model: str, pii_report: PiiDetectionReport | None = None) -> LLMReply:
    """Drain a streaming completion and return an LLMReply.

    Accumulates text tokens into content or assembles tool call fragments by
    index. Raises ValueError if the stream ends with neither content nor tool calls.
    """
    text_buf = ""
    tool_call_acc: dict[int, dict[str, str]] = {}
    finish_reason: str | None = None

    for chunk in stream:
        choice = chunk.choices[0] if chunk.choices else None
        if choice is None:
            continue
        if choice.finish_reason:
            finish_reason = choice.finish_reason
        delta = choice.delta
        if delta.content:
            text_buf += delta.content
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in tool_call_acc:
                    tool_call_acc[idx] = {"id": "", "name": "", "arguments_buf": ""}
                entry = tool_call_acc[idx]
                if tc_delta.id:
                    entry["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        entry["name"] += tc_delta.function.name
                    if tc_delta.function.arguments:
                        entry["arguments_buf"] += tc_delta.function.arguments

    if not text_buf and not tool_call_acc:
        raise ValueError("LLM 沒有回傳內容")

    if finish_reason == "tool_calls" or tool_call_acc:
        tool_calls = [
            LLMToolCall(
                id=tool_call_acc[idx]["id"],
                name=tool_call_acc[idx]["name"],
                arguments=tool_call_acc[idx]["arguments_buf"],
            )
            for idx in sorted(tool_call_acc)
        ]
        return LLMReply(content="", tool_calls=tool_calls, model=model, pii_report=pii_report)

    return LLMReply(content=text_buf.strip(), tool_calls=[], model=model, pii_report=pii_report)


def _stream_routes(
    routes: list[Any],
    messages: list[dict[str, Any]],
    cfg: Any,
    router: Any,
    create_kwargs: dict[str, Any],
    *,
    pii_report: PiiDetectionReport | None = None,
) -> LLMReply:
    """Legacy route loop for streaming when no fallback chain is configured."""
    errors: list[str] = []
    for route in routes:
        client = _get_sync_client(route.api_key, route.base_url)
        try:
            reply = _consume_stream(
                client.chat.completions.create(
                    model=route.model,
                    messages=cast(Any, messages),
                    temperature=cfg.llm_temperature,
                    stream=True,
                    **create_kwargs,
                ),
                model=route.model,
                pii_report=pii_report,
            )
            router.mark_success(route.api_key)
            return reply
        except ValueError:
            raise
        except Exception as exc:
            router.mark_failure(route.api_key, route.model, exc)
            errors.append(f"{route.model}: {type(exc).__name__}: {exc}")

    raise RuntimeError("所有 LLM route 皆失敗: " + " | ".join(errors))


def _build_create_kwargs(tools: list[dict[str, Any]] | None, *, forced_tool_name: str | None = None) -> dict[str, Any]:
    if not tools:
        return {}
    if forced_tool_name:
        tool_choice: str | dict[str, Any] = {"type": "function", "function": {"name": forced_tool_name}}
    else:
        tool_choice = "auto"
    return {"tools": tools, "tool_choice": tool_choice}


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

"""LLM client wrapper with bounded fallback chain execution."""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any, Protocol, cast

import httpx
from openai import OpenAI

from config import get_settings
from core.fallback_chain import (
    RouteHop,
    build_fallback_chain,
    has_admin_api_key,
    health_id,
)
from core.gemini_credentials import current_model_project, resolve_gemini_credential
from core.generation_cancel import (
    GenerationCancelled,
    is_cancelled,
    raise_if_cancelled,
)
from core.key_pool import (
    FAILURE_AUTH_FORBIDDEN,
    FAILURE_AUTH_INVALID,
    FAILURE_QUOTA_EXHAUSTED,
    FAILURE_TIMEOUT_CONNECT,
    FAILURE_TIMEOUT_FIRST_TOKEN,
    FAILURE_TIMEOUT_STALL,
    FAILURE_TIMEOUT_TOTAL,
    LLMTimeoutError,
    classify_failure,
    is_connect_timeout,
    is_timeout,
)
from core.provider_health import FailureKind, provider_health
from core.provider_router import LLMRoute, get_provider_router
from core.turn_budget import (
    current_trace_id,
    current_turn_budget,
    error_fields,
    number_setting,
)
from core.usage import LLMUsage, usage_from_response
from infra.usage_ledger import record_usage_event
from safety.observability import (
    log_event,
    record_chain_exhausted,
    record_fallback_hop,
    record_route_attempt,
)

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
        client = OpenAI(
            api_key=api_key,
            base_url=base_url or None,
            timeout=get_settings().llm_request_timeout_seconds,
            max_retries=0,
        )
        _SYNC_CLIENT_CACHE[key] = client
        if len(_SYNC_CLIENT_CACHE) > _CLIENT_CACHE_MAX:
            _SYNC_CLIENT_CACHE.popitem(last=False)
        return client


_HEALTH_KINDS: dict[str, FailureKind] = {
    FAILURE_AUTH_INVALID: "auth",
    FAILURE_AUTH_FORBIDDEN: "auth",
    FAILURE_QUOTA_EXHAUSTED: "quota",
}


# 剩不到這麼多預算就不開下一站：開了也只會在連線或第一個字前被切掉。
_MIN_HOP_SECONDS = 0.5
BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True, slots=True)
class _HopLimits:
    """Timeouts for one provider attempt.

    *read* is the socket read timeout. For a stream httpx applies it to every read,
    so it is both the wait for the first token and the longest gap between chunks;
    *total* caps the whole stream's wall-clock time. For a non-stream call *read* is
    the wait for the whole response.
    """

    mode: str
    connect: float
    read: float
    total: float

    def httpx_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(connect=self.connect, read=self.read, write=self.read, pool=self.connect)

    def log_fields(self) -> dict[str, Any]:
        return {"mode": self.mode, "timeout_s": round(self.read, 3)}


class _ChainClock:
    """Per-call budget across hops while a chat turn is bound (``core.turn_budget``).

    Outside a chat turn (graph extraction, summaries) there is no cross-hop budget
    and non-stream hops keep ``llm_request_timeout_seconds``.
    """

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg
        self.started = monotonic()
        self.in_turn = current_turn_budget() is not None
        self.deadline = (
            self.started + number_setting(cfg, "llm_first_token_budget_seconds", 15.0)
            if self.in_turn
            else None
        )

    def remaining(self) -> float | None:
        return None if self.deadline is None else self.deadline - monotonic()

    def limits(self, *, stream: bool) -> _HopLimits | None:
        """Limits for the next hop, or None when the budget cannot fit another hop."""
        cfg = self.cfg
        connect = number_setting(cfg, "llm_connect_timeout_seconds", 3.0)
        total = number_setting(cfg, "llm_request_timeout_seconds", 20.0)
        if stream:
            read = number_setting(cfg, "llm_first_token_timeout_seconds", 7.0)
        elif self.in_turn:
            read = number_setting(cfg, "llm_nonstream_timeout_seconds", 10.0)
        else:
            read = total
        remaining = self.remaining()
        if remaining is not None:
            if remaining < _MIN_HOP_SECONDS:
                return None
            connect, read = min(connect, remaining), min(read, remaining)
        return _HopLimits(
            mode="stream" if stream else "nonstream",
            connect=connect,
            read=read,
            total=max(total, read),
        )


@dataclass(slots=True)
class _StreamProgress:
    """What one streamed hop delivered before it ended, for timeout codes and logs."""

    started: float
    first_token_at: float | None = None
    streamed_chars: int = 0

    def first_token_ms(self) -> float | None:
        if self.first_token_at is None:
            return None
        return round((self.first_token_at - self.started) * 1000, 2)


def _timeout_error(
    exc: BaseException, limits: _HopLimits, progress: _StreamProgress | None, started: float,
) -> LLMTimeoutError:
    waited = monotonic() - started
    if is_connect_timeout(exc):
        return LLMTimeoutError(FAILURE_TIMEOUT_CONNECT, limit_s=limits.connect, waited_s=waited)
    if progress is None:
        return LLMTimeoutError(FAILURE_TIMEOUT_TOTAL, limit_s=limits.read, waited_s=waited)
    reason = FAILURE_TIMEOUT_STALL if progress.first_token_at is not None else FAILURE_TIMEOUT_FIRST_TOKEN
    return LLMTimeoutError(reason, limit_s=limits.read, waited_s=waited)


def _run_stream_hop(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, Any]],
    cfg: Any,
    create_kwargs: dict[str, Any],
    limits: _HopLimits,
    progress: _StreamProgress,
    text_listener: TextDeltaListener | None,
) -> LLMReply:
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=cast(Any, messages),
            temperature=cfg.llm_temperature,
            stream=True,
            timeout=limits.httpx_timeout(),
            **create_kwargs,
        )
        return _consume_stream(
            stream,
            model=model,
            text_listener=text_listener,
            progress=progress,
            total_deadline=progress.started + limits.total,
            total_limit=limits.total,
        )
    except LLMTimeoutError:
        raise
    except Exception as exc:
        if is_timeout(exc):
            raise _timeout_error(exc, limits, progress, progress.started) from exc
        raise


def _run_nonstream_hop(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, Any]],
    cfg: Any,
    create_kwargs: dict[str, Any],
    limits: _HopLimits,
) -> Any:
    started = monotonic()
    try:
        return client.chat.completions.create(
            model=model,
            messages=cast(Any, messages),
            temperature=cfg.llm_temperature,
            timeout=limits.httpx_timeout(),
            **create_kwargs,
        )
    except Exception as exc:
        if is_timeout(exc):
            raise _timeout_error(exc, limits, None, started) from exc
        raise


def _record_budget_exhausted(
    trace_id: str, clock: _ChainClock, chain: list[RouteHop], next_index: int,
) -> None:
    skipped = [f"{hop.provider}:{hop.model}" for hop in chain[next_index:]]
    log_event(
        "llm_chain_budget_exhausted",
        trace_id=trace_id,
        node="llm_chain",
        outcome=BUDGET_EXHAUSTED,
        elapsed_ms=round((monotonic() - clock.started) * 1000, 2),
        budget_s=number_setting(clock.cfg, "llm_first_token_budget_seconds", 15.0),
        skipped_hops=skipped,
    )


def _require_api_key() -> None:
    """Raise early if neither the deployment nor the Admin configured an LLM key."""
    if get_settings().resolved_llm_api_keys:
        return
    if has_admin_api_key():
        return
    raise ValueError("BRAIN_LLM_API_KEY / BRAIN_LLM_API_KEYS 尚未設定")


# forced_tool_name 的哨兵值：第一輪必須用工具，但不指定是哪一個。
REQUIRE_ANY_TOOL = "*"


@dataclass(frozen=True, slots=True)
class LLMToolCall:
    id: str
    name: str
    arguments: str
    extra_content: dict[str, Any] | None = None


class LLMEmptyReplyError(ValueError):
    """模型回了空內容——沒有文字也沒有 tool call。

    這是模型端的暫時性故障，不是使用者請求有誤。保持是 ValueError 的子類是刻意的：
    fallback chain 用 ``except ValueError: raise`` 讓空回覆不在下一個 hop 重試，
    改型別會讓那條路悄悄變成「換 provider 再試一次」。
    """


class TextDeltaListener(Protocol):
    """Receives a streamed turn's text as it arrives (``/brain/chat/stream``).

    ``attempt_started`` runs before every provider attempt, so text from a hop that
    failed mid-stream is not mistaken for the start of the next hop's answer.
    ``text_delta`` stops being called once the turn turns out to be a tool call.
    """

    def attempt_started(self) -> None: ...

    def text_delta(self, delta: str) -> None: ...


@dataclass(frozen=True, slots=True)
class LLMReply:
    content: str
    tool_calls: list[LLMToolCall]
    model: str
    usage: LLMUsage | None = None


def _record_llm_usage(
    provider: str,
    model: str,
    usage: LLMUsage | None,
    latency_ms: float,
    hop: RouteHop | None = None,
) -> None:
    # 沒回 usage 也記一筆零值，之後才看得出哪個 provider 不回報。
    raw: dict[str, Any] = {} if usage is not None else {"usage_missing": True}
    if hop is not None and hop.credential_source:
        raw.update(credential_source=hop.credential_source, credential_id=hop.credential_id)
    record_usage_event(
        provider=provider,
        model=model,
        usage=usage,
        latency_ms=latency_ms,
        raw=raw or None,
    )


def _stream_usage_kwargs(cfg: Any) -> dict[str, Any]:
    if getattr(cfg, "llm_stream_include_usage", True):
        return {"stream_options": {"include_usage": True}}
    return {}


def generate_chat_reply(
    messages: list[dict[str, Any]],
    *,
    model_override: str | None = None,
    trace_id: str = "",
) -> str:
    """Generate a chat reply using the configured provider."""
    return generate_chat_turn(
        messages,
        model_override=model_override,
        trace_id=trace_id,
    ).content.strip()


def generate_chat_turn(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    trace_id: str = "",
    model_override: str | None = None,
    forced_tool_name: str | None = None,
    max_tokens: int | None = None,
) -> LLMReply:
    """Request one non-stream chat completion turn with fallback chain."""
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
            arguments=_normalize_tool_arguments(tool_call.function.arguments),
            extra_content=_extract_tool_call_extra_content(tool_call),
        )
        for tool_call in (message.tool_calls or [])
    ]
    if not content and not tool_calls:
        raise LLMEmptyReplyError("LLM 沒有回傳內容")
    return LLMReply(
        content=content,
        tool_calls=tool_calls,
        model=response.model,
        usage=usage_from_response(getattr(response, "usage", None)),
    )


def stream_chat_turn(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    trace_id: str = "",
    model_override: str | None = None,
    forced_tool_name: str | None = None,
    max_tokens: int | None = None,
    text_listener: TextDeltaListener | None = None,
) -> LLMReply:
    """Stream one chat turn; detect tool calls vs text without a second round-trip.

    Identical return type and signature to generate_chat_turn — callers need no changes.
    Reuses the provider fallback chain and key-pool infrastructure. *text_listener*
    sees the text deltas while they arrive.
    """
    _require_api_key()
    cfg = get_settings()
    router = get_provider_router()
    tid = trace_id or current_trace_id() or uuid.uuid4().hex[:12]
    clock = _ChainClock(cfg)

    gemini_client = _get_gemini_client()
    chain, legacy_routes = _resolve_chain_or_routes(tid, client=gemini_client)
    chain, legacy_routes = _apply_model_override(chain, legacy_routes, model_override)

    create_kwargs = _build_create_kwargs(tools, forced_tool_name=forced_tool_name)
    if max_tokens:
        create_kwargs["max_tokens"] = max_tokens

    create_kwargs.update(_stream_usage_kwargs(cfg))

    if legacy_routes:
        return _stream_routes(
            legacy_routes, messages, cfg, router, create_kwargs,
            text_listener=text_listener, clock=clock,
        )

    errors: list[str] = []
    last_reason = ""
    for position, hop in enumerate(chain):
        # 用戶端已離開就不再換下一站重試。
        raise_if_cancelled("llm_call")
        limits = clock.limits(stream=True)
        if limits is None:
            _record_budget_exhausted(tid, clock, chain, position)
            last_reason = BUDGET_EXHAUSTED
            break
        if text_listener is not None:
            text_listener.attempt_started()
        t0 = _now_ms()
        progress = _StreamProgress(started=monotonic())
        client = _get_sync_client(hop.api_key, hop.base_url)
        try:
            reply = _run_stream_hop(
                client,
                model=hop.model,
                messages=messages,
                cfg=cfg,
                create_kwargs=create_kwargs,
                limits=limits,
                progress=progress,
                text_listener=text_listener,
            )
            router.mark_success(hop.api_key)
            provider_health().record_success(health_id(hop.provider, hop.model, hop.api_key))
            _record_llm_usage(hop.provider, hop.model, reply.usage, _now_ms() - t0, hop)
            record_route_attempt(
                trace_id=tid,
                provider=hop.provider,
                model=hop.model,
                hop_index=hop.hop_index,
                result="success",
                latency_ms=_now_ms() - t0,
                chain_length=len(chain),
                first_token_ms=progress.first_token_ms(),
                **limits.log_fields(),
            )
            return reply
        except (ValueError, GenerationCancelled):
            raise
        except Exception as exc:
            last_reason = _record_hop_failure(
                hop, exc, _now_ms() - t0, chain, errors, tid,
                details={
                    **limits.log_fields(),
                    "first_token_ms": progress.first_token_ms(),
                    "streamed_chars": progress.streamed_chars,
                },
            )
            if progress.streamed_chars and position + 1 < len(chain):
                # 已經有句子送到用戶端：照舊換下一站重答，ReplyStream.finish 會把整段補送；
                # 這裡留紀錄，log 才看得出那一輪的答案是兩站拼起來的。
                log_event(
                    "llm_restart_after_partial_text",
                    trace_id=tid,
                    provider=hop.provider,
                    model=hop.model,
                    hop_index=hop.hop_index,
                    reason=last_reason,
                    streamed_chars=progress.streamed_chars,
                )

    _raise_chain_exhausted(tid, errors, last_reason, len(chain))
    raise RuntimeError("unreachable")


def _get_gemini_client() -> Any:
    """Helper to lazily initialize the Gemini client if config supports it."""
    project_id = current_model_project()
    gemini_key = (
        resolve_gemini_credential(project_id).api_key if project_id is not None
        else get_settings().resolve_api_key_for_provider("gemini")
    )
    try:
        from google import genai
        if gemini_key:
            return genai.Client(api_key=gemini_key)
    except Exception:
        pass
    return None


def _resolve_chain_or_routes(
    trace_id: str,
    client: Any | None = None,
) -> tuple[list[RouteHop], list[LLMRoute]]:
    """Resolve the fallback chain; fall back to legacy routes if empty.

    Returns (chain, legacy_routes) where exactly one list is non-empty.
    Raises RuntimeError if neither source has available routes.
    """
    chain = build_fallback_chain(trace_id, client=client)
    if chain:
        return chain, []

    if current_model_project() is not None:
        # Legacy routes are process-global and can contain another project's shared key.
        raise RuntimeError("無可用的專案 LLM route")

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
    details: dict[str, Any] | None = None,
) -> str:
    """Shared failure handling for a single hop. Returns the failure reason."""
    reason = classify_failure(exc)
    router = get_provider_router()
    router.mark_failure(hop.api_key, hop.model, exc)
    provider_health().record_failure(
        health_id(hop.provider, hop.model, hop.api_key), _HEALTH_KINDS.get(reason, "transient"), reason,
    )

    record_route_attempt(
        trace_id=trace_id,
        provider=hop.provider,
        model=hop.model,
        hop_index=hop.hop_index,
        result="failure",
        latency_ms=latency_ms,
        reason=reason,
        chain_length=len(chain),
        **(details or {}),
        **error_fields(exc),
    )
    failure = error_fields(exc)
    errors.append(
        f"hop{hop.hop_index} {hop.provider}:{hop.model}: "
        f"{failure['error_type']}: {failure['error']}"
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
    tid = trace_id or current_trace_id() or uuid.uuid4().hex[:12]
    clock = _ChainClock(cfg)

    gemini_client = _get_gemini_client()
    chain, legacy_routes = _resolve_chain_or_routes(tid, client=gemini_client)
    chain, legacy_routes = _apply_model_override(
        chain,
        legacy_routes,
        model_override,
    )

    if legacy_routes:
        return _try_routes_sync(
            legacy_routes,
            messages,
            tools,
            cfg,
            router,
            forced_tool_name=forced_tool_name,
            max_tokens=max_tokens,
            clock=clock,
        )

    errors: list[str] = []
    last_reason = ""
    create_kwargs = _build_create_kwargs(tools, forced_tool_name=forced_tool_name)
    if max_tokens:
        create_kwargs["max_tokens"] = max_tokens

    for position, hop in enumerate(chain):
        raise_if_cancelled("llm_call")
        limits = clock.limits(stream=False)
        if limits is None:
            _record_budget_exhausted(tid, clock, chain, position)
            last_reason = BUDGET_EXHAUSTED
            break
        t0 = _now_ms()
        client = _get_sync_client(hop.api_key, hop.base_url)
        try:
            response = _run_nonstream_hop(
                client,
                model=hop.model,
                messages=messages,
                cfg=cfg,
                create_kwargs=create_kwargs,
                limits=limits,
            )
            router.mark_success(hop.api_key)
            provider_health().record_success(health_id(hop.provider, hop.model, hop.api_key))
            _record_llm_usage(
                hop.provider,
                hop.model,
                usage_from_response(getattr(response, "usage", None)),
                _now_ms() - t0,
                hop,
            )
            record_route_attempt(
                trace_id=tid,
                provider=hop.provider,
                model=hop.model,
                hop_index=hop.hop_index,
                result="success",
                latency_ms=_now_ms() - t0,
                chain_length=len(chain),
                **limits.log_fields(),
            )
            return response
        except Exception as exc:
            last_reason = _record_hop_failure(
                hop, exc, _now_ms() - t0, chain, errors, tid, details=limits.log_fields(),
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
            credential_source=hop.credential_source,
            credential_id=hop.credential_id,
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


def _try_routes_sync(
    routes: list[LLMRoute],
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    cfg: Any,
    router: Any,
    *,
    forced_tool_name: str | None = None,
    max_tokens: int | None = None,
    clock: _ChainClock | None = None,
) -> Any:
    """Legacy route loop for when no fallback chain is configured."""
    clock = clock or _ChainClock(cfg)
    errors: list[str] = []
    create_kwargs = _build_create_kwargs(tools, forced_tool_name=forced_tool_name)
    if max_tokens:
        create_kwargs["max_tokens"] = max_tokens
    provider = str(getattr(cfg, "llm_provider", "") or "")
    for route in routes:
        raise_if_cancelled("llm_call")
        limits = clock.limits(stream=False)
        if limits is None:
            errors.append(BUDGET_EXHAUSTED)
            break
        client = _get_sync_client(route.api_key, route.base_url)
        t0 = _now_ms()
        try:
            response = _run_nonstream_hop(
                client,
                model=route.model,
                messages=messages,
                cfg=cfg,
                create_kwargs=create_kwargs,
                limits=limits,
            )
            router.mark_success(route.api_key)
            _record_llm_usage(
                provider,
                route.model,
                usage_from_response(getattr(response, "usage", None)),
                _now_ms() - t0,
            )
            return response
        except Exception as exc:
            router.mark_failure(route.api_key, route.model, exc)
            failure = error_fields(exc)
            errors.append(f"{route.model}: {failure['error_type']}: {failure['error']}")

    raise RuntimeError("所有 LLM route 皆失敗: " + " | ".join(errors))


def _consume_stream(
    stream: Any,
    *,
    model: str,
    text_listener: TextDeltaListener | None = None,
    progress: _StreamProgress | None = None,
    total_deadline: float | None = None,
    total_limit: float = 0.0,
) -> LLMReply:
    """Drain a streaming completion and return an LLMReply.

    Accumulates text tokens into content or assembles tool call fragments by
    index. Raises ValueError if the stream ends with neither content nor tool calls.
    Text deltas go to *text_listener* until the first tool-call fragment shows up:
    a tool-call turn's text is discarded, so it must not reach the caller either.
    *progress* records when the first token arrived and how much text reached the
    listener; past *total_deadline* the stream is closed (``timeout_total``) even
    if it is still dripping.
    """
    text_buf = ""
    tool_call_acc: dict[int, dict[str, str]] = {}
    finish_reason: str | None = None
    usage: LLMUsage | None = None

    for chunk in stream:
        if is_cancelled():
            # 關掉串流會中斷與 provider 的連線，剩下的 token 不再生成。
            close = getattr(stream, "close", None)
            if callable(close):
                close()
            raise GenerationCancelled("llm_stream")
        if total_deadline is not None and monotonic() > total_deadline:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
            started = progress.started if progress is not None else total_deadline - total_limit
            raise LLMTimeoutError(
                FAILURE_TIMEOUT_TOTAL, limit_s=total_limit, waited_s=monotonic() - started,
            )
        # include_usage 時最後一個 chunk 只有 usage、choices 為空。
        chunk_usage = usage_from_response(getattr(chunk, "usage", None))
        if chunk_usage is not None:
            usage = chunk_usage
        choice = chunk.choices[0] if chunk.choices else None
        if choice is None:
            continue
        if choice.finish_reason:
            finish_reason = choice.finish_reason
        delta = choice.delta
        if progress is not None and progress.first_token_at is None and (
            delta.content or delta.tool_calls
        ):
            progress.first_token_at = monotonic()
        if delta.tool_calls:
            text_listener = None
        if delta.content:
            text_buf += delta.content
            if text_listener is not None:
                text_listener.text_delta(delta.content)
                if progress is not None:
                    progress.streamed_chars += len(delta.content)
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index if tc_delta.index is not None else 0
                if idx not in tool_call_acc:
                    tool_call_acc[idx] = {
                        "id": "",
                        "name": "",
                        "arguments_buf": "",
                        "thought_signature": "",
                    }
                entry = tool_call_acc[idx]
                if tc_delta.id:
                    entry["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        entry["name"] += tc_delta.function.name
                    if tc_delta.function.arguments:
                        entry["arguments_buf"] += tc_delta.function.arguments
                if sig := _extract_thought_signature(tc_delta):
                    entry["thought_signature"] = sig

    if not text_buf and not tool_call_acc:
        raise LLMEmptyReplyError("LLM 沒有回傳內容")

    if finish_reason == "tool_calls" or tool_call_acc:
        tool_calls = [
            LLMToolCall(
                id=tool_call_acc[idx]["id"],
                name=tool_call_acc[idx]["name"],
                arguments=_normalize_tool_arguments(tool_call_acc[idx]["arguments_buf"]),
                extra_content=(
                    {"thought_signature": tool_call_acc[idx]["thought_signature"]}
                    if tool_call_acc[idx].get("thought_signature")
                    else None
                ),
            )
            for idx in sorted(tool_call_acc)
        ]
        return LLMReply(content="", tool_calls=tool_calls, model=model, usage=usage)

    return LLMReply(content=text_buf.strip(), tool_calls=[], model=model, usage=usage)


def _stream_routes(
    routes: list[Any],
    messages: list[dict[str, Any]],
    cfg: Any,
    router: Any,
    create_kwargs: dict[str, Any],
    *,
    text_listener: TextDeltaListener | None = None,
    clock: _ChainClock | None = None,
) -> LLMReply:
    """Legacy route loop for streaming when no fallback chain is configured."""
    clock = clock or _ChainClock(cfg)
    errors: list[str] = []
    provider = str(getattr(cfg, "llm_provider", "") or "")
    for route in routes:
        raise_if_cancelled("llm_call")
        limits = clock.limits(stream=True)
        if limits is None:
            errors.append(BUDGET_EXHAUSTED)
            break
        if text_listener is not None:
            text_listener.attempt_started()
        client = _get_sync_client(route.api_key, route.base_url)
        t0 = _now_ms()
        try:
            reply = _run_stream_hop(
                client,
                model=route.model,
                messages=messages,
                cfg=cfg,
                create_kwargs=create_kwargs,
                limits=limits,
                progress=_StreamProgress(started=monotonic()),
                text_listener=text_listener,
            )
            router.mark_success(route.api_key)
            _record_llm_usage(provider, route.model, reply.usage, _now_ms() - t0)
            return reply
        except (ValueError, GenerationCancelled):
            raise
        except Exception as exc:
            router.mark_failure(route.api_key, route.model, exc)
            failure = error_fields(exc)
            errors.append(f"{route.model}: {failure['error_type']}: {failure['error']}")

    raise RuntimeError("所有 LLM route 皆失敗: " + " | ".join(errors))


def _build_create_kwargs(
    tools: list[dict[str, Any]] | None,
    *,
    forced_tool_name: str | None = None,
) -> dict[str, Any]:
    if not tools:
        return {}
    if forced_tool_name == REQUIRE_ANY_TOOL:
        # 一定要呼叫工具，但讓模型自己決定叫哪些、可以一次叫多個。
        tool_choice: str | dict[str, Any] = "required"
    elif forced_tool_name:
        tool_choice = {
            "type": "function",
            "function": {"name": forced_tool_name},
        }
    else:
        tool_choice = "auto"
    return {"tools": tools, "tool_choice": tool_choice}


def _now_ms() -> float:
    """Return monotonic time in milliseconds."""
    return monotonic() * 1000


def _normalize_tool_arguments(raw: str | None) -> str:
    """Gemini 的 OpenAI 相容端點拒收歷史裡 arguments 為空字串的 tool call（400
    INVALID_ARGUMENT），而模型偶爾會吐出不帶參數的呼叫；這筆一旦寫回對話歷史，
    下一輪整個請求就失敗。統一成 "{}"，參數缺漏交給工具的 schema 驗證回報。"""
    return raw if raw and raw.strip() else "{}"


def _extract_thought_signature(obj: Any) -> str | None:
    """Extract Google thought_signature from a tool call or delta object."""
    if not obj:
        return None
    if isinstance(obj, dict):
        if sig := obj.get("thought_signature") or obj.get("thought"):
            return str(sig)
        if google := obj.get("google"):
            if isinstance(google, dict) and (sig := google.get("thought_signature")):
                return str(sig)
        if extra := obj.get("extra_content"):
            return _extract_thought_signature(extra)
        return None

    if hasattr(obj, "thought_signature") and (sig := getattr(obj, "thought_signature", None)):
        return str(sig)

    for attr in ("extra_content", "model_extra"):
        val = getattr(obj, attr, None)
        if val and (sig := _extract_thought_signature(val)):
            return sig

    if hasattr(obj, "function"):
        fn = getattr(obj, "function", None)
        if fn and (sig := _extract_thought_signature(fn)):
            return sig

    return None


def _extract_tool_call_extra_content(tool_call: Any) -> dict[str, Any] | None:
    if sig := _extract_thought_signature(tool_call):
        return {"thought_signature": sig}
    return None

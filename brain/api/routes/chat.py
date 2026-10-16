from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response, StreamingResponse

from core.chat_service import (
    execute_generation,
    finalize_generation,
    prepare_generation,
    record_generation_failure,
    reply_media,
)
from core.chat_turns import accept_turn, register_turn, stage_turn
from core.decision_router import DecisionProviderCancelled
from core.generation_cancel import (
    GenerationCancelled,
    bind_cancel_event,
    raise_if_cancelled,
)
from core.llm_client import LLMEmptyReplyError
from core.reply_modes import DEFAULT_MODE, available_modes
from core.reply_stream import ReplyStream
from core.slash_command import try_rewrite_slash
from core.sse_events import (
    build_exception_protocol_error,
    build_protocol_error,
)
from core.usage import UsageScope, summarize_collected, usage_scope
from infra.client_disconnect import wait_for_client_disconnect
from protocol.history import serialize_history_messages
from protocol.message_envelope import (
    METADATA_ORIGINAL_USER_MESSAGE,
    build_message_envelope,
    merge_metadata,
)
from protocol.protocol_events import ProtocolValidationError
from protocol.schemas import ChatRequest, ChatResponse, ChatTurnAcceptRequest
from safety.guardrails import RequestRateLimitedError
from safety.internal_auth import (
    PRINCIPAL_ID_HEADER,
    PRINCIPAL_TYPE_HEADER,
    USER_ID_HEADER,
    USER_ROLE_HEADER,
    may_see_decision_debug,
    require_internal_token,
)
from safety.observability import get_metrics_store, log_event, log_exception
from tools.skill_manager import get_skill_manager

logger = logging.getLogger("brain.chat")

router = APIRouter(
    prefix="/brain",
    tags=["Chat"],
    dependencies=[Depends(require_internal_token)],
)


def _maybe_rewrite_slash(payload: ChatRequest) -> dict[str, Any]:
    raw = payload.model_dump()
    slash = try_rewrite_slash(
        raw["message"],
        get_skill_manager(),
        project_id=raw.get("project_id") or "default",
    )
    if slash is not None:
        raw["metadata"] = merge_metadata(
            raw.get("metadata"),
            {METADATA_ORIGINAL_USER_MESSAGE: raw["message"]},
        )
        raw["message"] = slash.rewritten
    return raw


def _decision_debug_requested(request: Request, payload: ChatRequest) -> bool:
    return bool(payload.decision_debug) and may_see_decision_debug(
        request.headers.get(USER_ROLE_HEADER, ""),
        request.headers.get(PRINCIPAL_TYPE_HEADER, ""),
    )


def _prepare_chat_context(request: Request, payload: ChatRequest) -> Any:
    raw = _maybe_rewrite_slash(payload)
    envelope = build_message_envelope(request, raw, content_key="message")
    return prepare_generation(
        envelope, reply_mode=payload.mode, decision_debug=_decision_debug_requested(request, payload),
        preferred_language=payload.preferred_language,
    )


def _log_generation_success(context: Any, tool_steps: int) -> None:
    log_event(
        "chat_complete",
        trace_id=context.trace_id,
        session_id=context.session_id,
        tool_steps=tool_steps,
        project_id=context.project_id,
    )


def _handle_generation_error(exc: Exception, action: str, request: Request) -> NoReturn:
    trace_id = getattr(request.state, "trace_id", "")
    # 模型回空是伺服器端的暫時性故障，跟 guardrail 擋下的壞請求是兩回事：回 400
    # 會讓前端不重試、監控把它算成 guardrail block。它是 ValueError 的子類，所以要
    # 排在下面那個泛用判斷前面。
    if isinstance(exc, LLMEmptyReplyError):
        log_exception(f"{action}_empty_reply", exc, trace_id=trace_id)
        record_generation_failure(action, "llm_failure", str(exc))
        error_payload = build_protocol_error("LLM_OVERLOAD", "LLM 生成失敗", retry_after_ms=3000)
        raise HTTPException(status_code=502, detail=error_payload) from exc

    # 限流也是 ValueError，但它不是請求內容有問題：標成 INVALID_REQUEST 會叫串接端
    # 改寫問題，實際上該等一下再送。
    if isinstance(exc, RequestRateLimitedError):
        record_generation_failure(action, "rate_limited", str(exc))
        error_payload = build_protocol_error(
            "LLM_OVERLOAD", str(exc), retry_after_ms=exc.retry_after_seconds * 1000,
        )
        raise HTTPException(
            status_code=429,
            detail=error_payload,
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    if isinstance(exc, (ValueError, ProtocolValidationError)):
        # 這條路以前不記 log，錯誤訊息只進 metrics，出事時得靠推理拼回來。
        log_exception(f"{action}_rejected", exc, trace_id=trace_id)
        get_metrics_store().increment("guardrail_blocks_total", action=action)
        record_generation_failure(action, "validation", str(exc))
        raise HTTPException(status_code=400, detail=build_exception_protocol_error(exc)) from exc

    log_exception(f"{action}_error", exc, trace_id=trace_id)
    record_generation_failure(action, "llm_failure", str(exc))
    error_payload = build_protocol_error("LLM_OVERLOAD", "LLM 生成失敗", retry_after_ms=3000)
    raise HTTPException(status_code=502, detail=error_payload) from exc


# nginx 的慣例：用戶端先斷線。對方已經不在，這個狀態碼只會進 log。
_CLIENT_CLOSED_REQUEST = 499


async def _cancel_on_disconnect(request: Request, cancel_event: threading.Event) -> None:
    await wait_for_client_disconnect(request)
    cancel_event.set()


def _log_chat_cancelled(
    request: Request,
    payload: ChatRequest,
    exc: Exception,
    *,
    context: Any,
    scope: UsageScope | None,
    started: float,
) -> None:
    if isinstance(exc, GenerationCancelled):
        stage, tool_steps = exc.stage, exc.tool_steps
    elif isinstance(exc, DecisionProviderCancelled):
        stage, tool_steps = "turn_decision", 0
    else:
        stage, tool_steps = f"error:{type(exc).__name__}", 0
    log_event(
        "chat_cancelled",
        trace_id=(
            getattr(context, "trace_id", "")
            or getattr(request.state, "trace_id", "")
        ),
        session_id=payload.session_id or "",
        project_id=payload.project_id or "default",
        turn_id=payload.turn_id or "",
        stage=stage,
        tool_steps=tool_steps,
        llm_calls=len(scope.collected) if scope is not None else 0,
        elapsed_s=round(time.monotonic() - started, 2),
    )


@dataclass(slots=True)
class _ChatRun:
    """What a cancelled or failed turn's log line needs from the generation so far."""

    started: float = field(default_factory=time.monotonic)
    context: Any = None
    scope: UsageScope | None = None


async def _generate_chat_response(
    request: Request,
    payload: ChatRequest,
    cancel_event: threading.Event,
    run: _ChatRun,
    reply_stream: ReplyStream | None = None,
) -> dict[str, Any]:
    """Run one chat turn and build the /chat payload; shared by /chat and /chat/stream."""
    with bind_cancel_event(cancel_event):
        if payload.turn_id is not None:
            await asyncio.to_thread(register_turn, request, payload)
        logger.info("[CHAT] User Session: %s Project: %s Message: %r", payload.session_id, payload.project_id, payload.message)

        # 用量歸屬：prepare 階段（recall 摘要、query expansion）也會呼叫 LLM，
        # 所以 scope 要在 prepare 之前開，拿到正式 context 後再補齊 id。
        with usage_scope(
            kind="chat",
            user_id=request.headers.get(USER_ID_HEADER, ""),
            role=request.headers.get(USER_ROLE_HEADER, ""),
            principal_type=request.headers.get(PRINCIPAL_TYPE_HEADER, "") or "user",
            principal_id=(
                request.headers.get(PRINCIPAL_ID_HEADER, "")
                or request.headers.get(USER_ID_HEADER, "")
            ),
            project_id=payload.project_id or "default",
            session_id=payload.session_id or "",
            persona_id=payload.persona_id or "default",
        ) as scope:
            run.scope = scope
            context = await asyncio.to_thread(_prepare_chat_context, request, payload)
            run.context = context
            scope.project_id = context.project_id
            scope.session_id = context.session_id
            scope.persona_id = context.persona_id
            scope.trace_id = context.trace_id
            scope.channel = str(context.request_context.get("channel", ""))
            if reply_stream is None:
                result = await asyncio.to_thread(execute_generation, context)
            else:
                result = await asyncio.to_thread(
                    execute_generation, context, text_listener=reply_stream,
                )
                # 句子先送完再挑圖、寫紀錄、判斷 no_answer：整合方的 TTS 不用等這些。
                if not cancel_event.is_set():
                    reply_stream.finish(result.reply)
            # 最後一次 LLM 呼叫可能在斷線後才跑完；答案沒人收就不挑圖、不寫紀錄。
            raise_if_cancelled("reply_media", tool_steps=len(result.tool_steps))
            media = await asyncio.to_thread(reply_media, context, result.tool_steps)
        raise_if_cancelled("persist", tool_steps=len(result.tool_steps))
        response_time_s = round(time.monotonic() - run.started, 2)
        if payload.turn_id is not None:
            response = await asyncio.to_thread(
                stage_turn, request, payload, context,
                result.reply, result.tool_steps, response_time_s, media,
            )
        else:
            response = finalize_generation(
                context, result.reply, result.tool_steps, response_time_s,
                media=media,
            )
    if _decision_debug_requested(request, payload) and context.turn_decision is not None:
        # Added after stage_turn: never persist emotional diagnostics in the delivery payload.
        response["decision_debug"] = context.turn_decision.to_debug_payload()
    response["tool_steps"] = result.tool_steps
    response["response_time_s"] = response_time_s
    response["usage"] = summarize_collected(scope)
    _log_generation_success(context, len(result.tool_steps))

    logger.info("[CHAT] AI Reply: %r (Time: %ss)", result.reply, response_time_s)
    return response


@router.post(
    "/chat",
    summary="非串流對話",
    responses={
        200: {
            "model": ChatResponse,
            "description": "回答。沒有回答語言欄位：要念台語請依 ASR 回傳的 language 決定 TTS",
        },
    },
)
async def chat(request: Request, payload: ChatRequest):
    # 用戶端斷線（數位人被打斷、整合方 abort fetch）就停止生成：不再開下一次 LLM
    # 呼叫或工具輪，也不寫對話紀錄。已送出的那一次 LLM 請求收不回來。
    run = _ChatRun()
    cancel_event = threading.Event()
    watcher = asyncio.create_task(_cancel_on_disconnect(request, cancel_event))
    try:
        return await _generate_chat_response(request, payload, cancel_event, run)
    except HTTPException:
        raise
    except (GenerationCancelled, DecisionProviderCancelled) as exc:
        _log_chat_cancelled(request, payload, exc, context=run.context, scope=run.scope, started=run.started)
        return Response(status_code=_CLIENT_CLOSED_REQUEST)
    except Exception as exc:
        if cancel_event.is_set():
            # 斷線後才冒出的錯誤（例如串流被關掉）是取消的結果，不算生成失敗。
            _log_chat_cancelled(request, payload, exc, context=run.context, scope=run.scope, started=run.started)
            return Response(status_code=_CLIENT_CLOSED_REQUEST)
        _handle_generation_error(exc, "chat", request)
    finally:
        watcher.cancel()


def _sse(event: str, data: Any) -> str:
    body = json.dumps(jsonable_encoder(data), ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n"


def _error_event(exc: HTTPException) -> tuple[str, dict[str, Any]]:
    return "error", {"status": exc.status_code, "detail": exc.detail}


# 用戶端走了以後生成還會跑到下一個安全點才停；任務要有人持有，否則可能被回收。
_background_runs: set[asyncio.Task[None]] = set()


async def _stream_chat_events(request: Request, payload: ChatRequest) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()

    def put(item: tuple[str, Any] | None) -> None:
        # 句子從生成執行緒送來；結果也走同一條 call_soon_threadsafe，順序才不會亂。
        loop.call_soon_threadsafe(queue.put_nowait, item)

    reply_stream = ReplyStream(lambda index, text: put(("sentence", {"index": index, "text": text})))
    run = _ChatRun()
    cancel_event = threading.Event()

    async def produce() -> None:
        try:
            response = await _generate_chat_response(
                request, payload, cancel_event, run, reply_stream,
            )
            put(("done", response))
        except (GenerationCancelled, DecisionProviderCancelled) as exc:
            _log_chat_cancelled(request, payload, exc, context=run.context, scope=run.scope, started=run.started)
            put(None)
        except HTTPException as exc:
            put(_error_event(exc))
        except Exception as exc:
            if cancel_event.is_set():
                _log_chat_cancelled(request, payload, exc, context=run.context, scope=run.scope, started=run.started)
                put(None)
                return
            try:
                _handle_generation_error(exc, "chat_stream", request)
            except HTTPException as http_exc:
                put(_error_event(http_exc))
                return
            # 錯誤一律以 error 事件收尾，不讓串流懸著。
            put(("error", {"status": 500, "detail": "Internal Server Error"}))
        except asyncio.CancelledError:
            put(None)
            raise

    watcher = asyncio.create_task(_cancel_on_disconnect(request, cancel_event))
    producer = asyncio.create_task(produce())
    _background_runs.add(producer)
    producer.add_done_callback(_background_runs.discard)
    try:
        while True:
            item = await queue.get()
            if item is None:
                return
            event, data = item
            yield _sse(event, data)
            if event != "sentence":
                return
    finally:
        # 用戶端中途離開時 StreamingResponse 會取消這個 generator：
        # 讓生成在下一個安全點停下來，跟 /chat 斷線一樣不寫紀錄。
        if not producer.done():
            cancel_event.set()
        watcher.cancel()


@router.post("/chat/stream", summary="逐句串流對話（SSE）")
async def chat_stream(request: Request, payload: ChatRequest):
    """Same turn as ``/chat``, sent as Server-Sent Events.

    ``sentence`` events carry the final answer one sentence at a time while the model
    writes it; ``done`` carries exactly what ``/chat`` returns; ``error`` carries
    ``{"status", "detail"}`` as ``/chat`` would have answered with that HTTP status.
    """
    return StreamingResponse(
        _stream_chat_events(request, payload),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/accept", summary="確認接收可合併回合的回答")
async def chat_accept(request: Request, payload: ChatTurnAcceptRequest):
    return await accept_turn(request, payload)


@router.get("/chat/modes", summary="可用的回覆深度模式")
async def chat_modes():
    """List the reply depth modes so clients don't hardcode them."""
    return {
        "default": DEFAULT_MODE,
        "modes": [
            {
                "name": mode.name,
                "label": mode.label,
                "max_followup_tool_rounds": mode.max_followup_tool_rounds,
                "allow_web_search": mode.allow_web_search,
            }
            for mode in available_modes()
        ],
    }


@router.get("/chat/history", summary="對話歷史")
async def chat_history(session_id: str, project_id: str = "default", persona_id: str = "default"):
    from memory.memory import list_session_messages

    messages = list_session_messages(session_id=session_id, persona_id=persona_id, project_id=project_id)
    history = serialize_history_messages(messages)
    return {"session_id": session_id, "persona_id": persona_id, "history": history}

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from core.chat_service import (
    GenerationContext,
    execute_generation,
    finalize_generation,
    prepare_generation,
    record_generation_failure,
    stream_generation,
)
from core.slash_command import try_rewrite_slash
from core.sse_events import (
    build_exception_protocol_error,
    build_protocol_error,
    sse_error_to_dict,
    sse_event_to_dict,
)
from protocol.message_envelope import (
    METADATA_ORIGINAL_USER_MESSAGE,
    build_message_envelope,
    merge_metadata,
)
from protocol.protocol_events import ProtocolValidationError
from protocol.schemas import ChatRequest
from safety.observability import get_metrics_store, log_event, log_exception
from tools.skill_manager import get_skill_manager

router = APIRouter(prefix="/brain", tags=["Chat"])


def _maybe_rewrite_slash(payload: ChatRequest) -> dict[str, Any]:
    raw = payload.model_dump()
    slash = try_rewrite_slash(raw["message"], get_skill_manager())
    if slash is not None:
        raw["metadata"] = merge_metadata(
            raw.get("metadata"),
            {METADATA_ORIGINAL_USER_MESSAGE: raw["message"]},
        )
        raw["message"] = slash.rewritten
    return raw


def _prepare_chat_context(request: Request, payload: ChatRequest) -> Any:
    raw = _maybe_rewrite_slash(payload)
    envelope = build_message_envelope(request, raw, content_key="message")
    return prepare_generation(envelope)


def _log_generation_success(context: Any, tool_steps: int) -> None:
    log_event(
        "chat_complete",
        trace_id=context.trace_id,
        session_id=context.session_id,
        tool_steps=tool_steps,
        project_id=context.project_id,
    )


def _handle_generation_error(exc: Exception, action: str, request: Request) -> NoReturn:
    if isinstance(exc, (ValueError, ProtocolValidationError)):
        get_metrics_store().increment("guardrail_blocks_total", action=action)
        record_generation_failure(action, "validation", str(exc))
        raise HTTPException(status_code=400, detail=build_exception_protocol_error(exc)) from exc

    log_exception(f"{action}_error", exc, trace_id=getattr(request.state, "trace_id", ""))
    record_generation_failure(action, "llm_failure", str(exc))
    error_payload = build_protocol_error("LLM_OVERLOAD", "LLM 生成失敗", retry_after_ms=3000)
    raise HTTPException(status_code=502, detail=error_payload) from exc


async def _stream_generation_events(context: GenerationContext) -> AsyncIterator[dict[str, str]]:
    try:
        tool_count = 0
        async for event in stream_generation(context):
            if event.event == "tool":
                tool_count += 1
                get_metrics_store().increment("tool_calls_total", tool_name=event.name)
            yield sse_event_to_dict(event)

        log_event(
            "chat_stream_complete",
            trace_id=context.trace_id,
            session_id=context.session_id,
            tool_steps=tool_count,
            project_id=context.project_id,
        )
    except asyncio.CancelledError:
        record_generation_failure("chat_stream", "cancelled", context.user_message[:120])
        raise
    except ValueError as exc:
        record_generation_failure("chat_stream", "validation", str(exc))
        yield sse_error_to_dict(build_exception_protocol_error(exc), context.trace_id)
    except Exception as exc:  # pragma: no cover
        log_exception("chat_stream_error", exc, trace_id=context.trace_id)
        record_generation_failure("chat_stream", "llm_failure", str(exc))
        yield sse_error_to_dict(
            build_protocol_error("LLM_OVERLOAD", "LLM 串流生成失敗", retry_after_ms=3000),
            context.trace_id,
        )


@router.post("/chat", summary="非串流對話")
async def chat(request: Request, payload: ChatRequest):
    try:
        context = _prepare_chat_context(request, payload)
        result = await asyncio.to_thread(execute_generation, context)
        response = finalize_generation(context, result.reply)
        response["tool_steps"] = result.tool_steps
        _log_generation_success(context, len(result.tool_steps))
        return response
    except Exception as exc:
        _handle_generation_error(exc, "chat", request)


@router.get("/chat/history", summary="對話歷史")
async def chat_history(session_id: str, project_id: str = "default", persona_id: str = "default"):
    from memory.memory import list_session_messages

    messages = list_session_messages(session_id=session_id, persona_id=persona_id, project_id=project_id)
    return {"session_id": session_id, "persona_id": persona_id, "history": messages}


@router.post("/chat/stream", summary="串流對話 (SSE)")
async def chat_stream(request: Request, payload: ChatRequest):
    try:
        context = _prepare_chat_context(request, payload)
        return EventSourceResponse(_stream_generation_events(context))
    except Exception as exc:
        _handle_generation_error(exc, "chat_stream", request)


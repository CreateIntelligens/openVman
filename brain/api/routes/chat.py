from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, NoReturn
from uuid import uuid4

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
from core.chat_shortcut import ChatShortcut, try_shortcut
from core.slash_command import try_rewrite_slash
from core.sse_events import (
    DoneEvent,
    SessionEvent,
    ToolEvent,
    build_exception_protocol_error,
    build_protocol_error,
    sse_error_to_dict,
    sse_event_to_dict,
)
from protocol.message_envelope import (
    METADATA_ACTION_REQUESTS,
    METADATA_ORIGINAL_USER_MESSAGE,
    build_message_envelope,
    merge_metadata,
)
from protocol.protocol_events import ProtocolValidationError
from protocol.schemas import ChatRequest
from memory.memory import append_session_message, get_or_create_session
from safety.observability import get_metrics_store, log_event, log_exception
from tools.skill_manager import get_skill_manager

router = APIRouter(prefix="/brain", tags=["Chat"])


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
    history: list[dict[str, Any]] = []
    for message in messages:
        metadata = message.get("metadata") if isinstance(message, dict) else None
        entry = {k: v for k, v in message.items() if k != "metadata"}
        if isinstance(metadata, dict):
            action_requests = metadata.get(METADATA_ACTION_REQUESTS)
            if isinstance(action_requests, list) and action_requests:
                entry[METADATA_ACTION_REQUESTS] = action_requests
        history.append(entry)
    return {"session_id": session_id, "persona_id": persona_id, "history": history}


async def _stream_shortcut_events(
    payload: ChatRequest,
    shortcut: ChatShortcut,
) -> AsyncIterator[dict[str, str]]:
    session = get_or_create_session(payload.session_id, payload.persona_id, project_id=payload.project_id)
    append_session_message(session.session_id, payload.persona_id, "user", payload.message, project_id=payload.project_id)

    step = shortcut.tool_step
    assistant_metadata: dict[str, Any] | None = None
    try:
        action_payload = json.loads(step.result)
        assistant_metadata = {METADATA_ACTION_REQUESTS: [action_payload]}
    except (ValueError, TypeError):
        assistant_metadata = None

    append_session_message(
        session.session_id,
        payload.persona_id,
        "assistant",
        shortcut.reply,
        project_id=payload.project_id,
        metadata=assistant_metadata,
    )

    trace_id = uuid4().hex
    yield sse_event_to_dict(SessionEvent(session_id=session.session_id, trace_id=trace_id))
    yield sse_event_to_dict(ToolEvent(
        trace_id=trace_id,
        tool_call_id=step.tool_call_id,
        name=step.name,
        arguments=step.arguments,
        result=step.result,
    ))
    yield sse_event_to_dict(DoneEvent(
        trace_id=trace_id,
        session_id=session.session_id,
        reply=shortcut.reply,
        knowledge_results=[],
        memory_results=[],
        tool_steps=[{
            "tool_call_id": step.tool_call_id,
            "name": step.name,
            "arguments": step.arguments,
            "result": step.result,
        }],
    ))


@router.post("/chat/stream", summary="串流對話 (SSE)")
async def chat_stream(request: Request, payload: ChatRequest):
    shortcut = try_shortcut(payload.message)
    if shortcut is not None:
        return EventSourceResponse(_stream_shortcut_events(payload, shortcut))
    try:
        context = _prepare_chat_context(request, payload)
        return EventSourceResponse(_stream_generation_events(context))
    except Exception as exc:
        _handle_generation_error(exc, "chat_stream", request)


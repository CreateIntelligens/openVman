from __future__ import annotations

import asyncio
import time
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request

from core.chat_service import (
    execute_generation,
    finalize_generation,
    prepare_generation,
    record_generation_failure,
)
from core.slash_command import try_rewrite_slash
from core.sse_events import (
    build_exception_protocol_error,
    build_protocol_error,
)
from protocol.message_envelope import (
    METADATA_ACTION_REQUESTS,
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


@router.post("/chat", summary="非串流對話")
async def chat(request: Request, payload: ChatRequest):
    try:
        t0 = time.monotonic()
        context = await asyncio.to_thread(_prepare_chat_context, request, payload)
        result = await asyncio.to_thread(execute_generation, context)
        response_time_s = round(time.monotonic() - t0, 2)
        response = finalize_generation(
            context, result.reply, result.tool_steps, response_time_s, result.pii_report,
        )
        response["tool_steps"] = result.tool_steps
        response["response_time_s"] = response_time_s
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
            tool_steps = metadata.get("tool_steps")
            if isinstance(tool_steps, list) and tool_steps:
                entry["tool_steps"] = tool_steps
            rts = metadata.get("response_time_s")
            if rts is not None:
                entry["response_time_s"] = rts
        history.append(entry)
    return {"session_id": session_id, "persona_id": persona_id, "history": history}


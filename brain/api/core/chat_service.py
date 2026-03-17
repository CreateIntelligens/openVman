"""Shared chat generation workflow for sync and streaming endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from config import get_settings
from core.agent_loop import AgentLoopResult, ToolPhaseError, prepare_agent_reply, run_agent_loop
from core.llm_client import generate_chat_reply, stream_chat_reply
from core.pipeline import RouteDecision, route_message
from core.prompt_builder import build_chat_messages
from core.sse_events import (
    ContextEvent,
    DoneEvent,
    SessionEvent,
    SSEEvent,
    TokenEvent,
    ToolErrorEvent,
    ToolEvent,
)
from infra.learnings import record_error_event
from memory.memory import (
    append_session_message,
    archive_session_turn,
    get_or_create_session,
    list_session_messages,
)
from memory.memory_governance import maybe_run_memory_maintenance
from protocol.message_envelope import MessageEnvelope, normalize_to_brain_message, serialize_context
from safety.guardrails import enforce_guardrails, enforce_session_limits
from tools.tool_executor import parse_tool_result


@dataclass(slots=True)
class GenerationContext:
    trace_id: str
    persona_id: str
    project_id: str
    session_id: str
    route: RouteDecision
    user_message: str
    request_context: dict[str, Any]
    prompt_messages: list[dict[str, str]]


def prepare_generation(envelope: MessageEnvelope) -> GenerationContext:
    """Build prompt inputs and update the user side of the session.

    Knowledge and memory retrieval is no longer done here — the LLM will
    call search_knowledge / search_memory tools during the agent loop.
    """
    cleaned_message = envelope.content.strip()
    cfg = get_settings()
    persona_id = envelope.context.persona_id
    project_id = envelope.context.project_id

    if not cleaned_message:
        raise ValueError("message 不可為空")
    if len(cleaned_message) > cfg.max_input_length:
        raise ValueError(f"message 不可超過 {cfg.max_input_length} 字")
    enforce_guardrails("chat", cleaned_message, envelope.context)
    enforce_session_limits(envelope.context.session_id, persona_id, project_id)

    route = route_message(normalize_to_brain_message(envelope))
    session = get_or_create_session(envelope.context.session_id, persona_id, project_id=project_id)
    prior_messages = list_session_messages(session.session_id, persona_id, project_id=project_id)
    append_session_message(session.session_id, persona_id, "user", cleaned_message, project_id=project_id)

    request_ctx = serialize_context(envelope.context)
    prompt_messages = build_chat_messages(
        user_message=cleaned_message,
        request_context=request_ctx,
        session_messages=prior_messages,
    )

    return GenerationContext(
        trace_id=envelope.context.trace_id,
        persona_id=persona_id,
        project_id=project_id,
        session_id=session.session_id,
        route=route,
        user_message=cleaned_message,
        request_context=request_ctx,
        prompt_messages=prompt_messages,
    )


def finalize_generation(context: GenerationContext, reply: str) -> dict[str, Any]:
    """Persist the assistant reply and return the standard API payload."""
    cleaned_reply = reply.strip()
    if not cleaned_reply:
        raise ValueError("LLM 沒有回傳內容")

    append_session_message(context.session_id, context.persona_id, "assistant", cleaned_reply, project_id=context.project_id)
    archive_session_turn(
        context.session_id,
        context.user_message,
        cleaned_reply,
        context.persona_id,
        project_id=context.project_id,
    )

    # Memory is now written by the LLM via the save_memory tool —
    # no automatic per-turn memory write here.
    maintenance = maybe_run_memory_maintenance(project_id=context.project_id)

    return {
        "status": "ok",
        "trace_id": context.trace_id,
        "session_id": context.session_id,
        "request_context": context.request_context,
        "reply": cleaned_reply,
        "history": list_session_messages(context.session_id, context.persona_id, project_id=context.project_id),
        "memory_maintenance": maintenance,
    }


_TOOL_FALLBACK_HINT = (
    "[系統提示] 工具流程部分失敗。請優先使用已成功取得的工具資訊回答使用者，"
    "若資訊不足，請誠實說明限制並提供安全的下一步建議。"
)


def _inject_tool_fallback_hint(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a new message list with a system hint inserted before the last user message.

    The original list is NOT mutated.
    """
    result = list(messages)
    insert_idx = len(result)
    for i in range(len(result) - 1, -1, -1):
        if result[i].get("role") == "user":
            insert_idx = i
            break
    result.insert(insert_idx, {"role": "system", "content": _TOOL_FALLBACK_HINT})
    return result


def _fallback_messages_for_tool_phase_error(
    context: GenerationContext,
    exc: ToolPhaseError,
) -> list[dict[str, Any]]:
    partial_messages = exc.partial_messages or context.prompt_messages
    return _inject_tool_fallback_hint(partial_messages)


def _tool_error_status_from_steps(tool_steps: list[dict[str, Any]]) -> str:
    if not tool_steps:
        return "phase_error"
    parsed = parse_tool_result(tool_steps[-1].get("result", ""))
    if parsed is None:
        return "phase_error"
    if "逾時" in parsed.error:
        return "timeout"
    if parsed.status == "error":
        return "error"
    return "phase_error"


def _tool_error_event_from_phase_error(trace_id: str, exc: ToolPhaseError) -> ToolErrorEvent:
    last_step = exc.partial_steps[-1] if exc.partial_steps else {}
    return ToolErrorEvent(
        trace_id=trace_id,
        error=str(exc),
        partial_steps_count=len(exc.partial_steps),
        tool_call_id=last_step.get("tool_call_id", ""),
        name=last_step.get("name", ""),
        status=_tool_error_status_from_steps(exc.partial_steps),
    )


def execute_generation(context: GenerationContext) -> AgentLoopResult:
    """Run the configured agent loop on top of prepared prompt messages."""
    if context.route.skip_tools:
        return AgentLoopResult(
            reply=generate_chat_reply(context.prompt_messages),
            tool_steps=[],
        )
    try:
        return run_agent_loop(context.prompt_messages, persona_id=context.persona_id, project_id=context.project_id)
    except ToolPhaseError as exc:
        fallback_messages = _fallback_messages_for_tool_phase_error(context, exc)
        reply = generate_chat_reply(fallback_messages)
        return AgentLoopResult(reply=reply, tool_steps=exc.partial_steps)


def _tool_event_from_step(trace_id: str, step: dict[str, Any]) -> ToolEvent:
    return ToolEvent(
        trace_id=trace_id,
        tool_call_id=step.get("tool_call_id", ""),
        name=step.get("name", ""),
        arguments=step.get("arguments", ""),
        result=step.get("result", ""),
    )


async def stream_generation(context: GenerationContext) -> AsyncIterator[SSEEvent]:
    """Stream a chat generation from prepared prompt context."""
    yield SessionEvent(session_id=context.session_id, trace_id=context.trace_id)

    reply_parts: list[str] = []
    tool_steps: list[dict[str, Any]] = []
    stream_messages: list[dict[str, Any]] = context.prompt_messages

    if not context.route.skip_tools:
        try:
            prepared = await asyncio.to_thread(
                prepare_agent_reply,
                context.prompt_messages,
                context.persona_id,
                context.project_id,
            )
            stream_messages = prepared.messages
            tool_steps = prepared.tool_steps
            for step in tool_steps:
                yield _tool_event_from_step(context.trace_id, step)
        except ToolPhaseError as exc:
            tool_steps = exc.partial_steps
            for step in tool_steps:
                yield _tool_event_from_step(context.trace_id, step)
            yield _tool_error_event_from_phase_error(context.trace_id, exc)
            stream_messages = _fallback_messages_for_tool_phase_error(context, exc)

    # Emit context event after tool phase so counts reflect actual tool usage
    knowledge_count, memory_count = _count_retrieval_from_tool_steps(tool_steps)
    yield ContextEvent(
        trace_id=context.trace_id,
        knowledge_count=knowledge_count,
        memory_count=memory_count,
        request_context=context.request_context,
    )

    async for token in stream_chat_reply(stream_messages):
        reply_parts.append(token)
        yield TokenEvent(trace_id=context.trace_id, token=token)

    full_reply = "".join(reply_parts)
    finalize_generation(context, full_reply)
    yield DoneEvent(
        trace_id=context.trace_id,
        session_id=context.session_id,
        reply=full_reply,
        knowledge_results=[],
        memory_results=[],
        tool_steps=tool_steps,
    )


def _count_retrieval_from_tool_steps(tool_steps: list[dict[str, Any]]) -> tuple[int, int]:
    """Count knowledge and memory results from completed tool call steps."""
    knowledge_count = 0
    memory_count = 0
    for step in tool_steps:
        name = step.get("name", "")
        parsed = parse_tool_result(step.get("result", ""))
        if parsed is None or parsed.status != "ok":
            continue
        result_count = len(parsed.data.get("results", []))
        if name == "search_knowledge":
            knowledge_count += result_count
        elif name == "search_memory":
            memory_count += result_count
    return knowledge_count, memory_count


def record_generation_failure(area: str, message: str, detail: str = "") -> None:
    """Store a summarized failure entry into ERRORS.md."""
    record_error_event(area=area, summary=message, detail=detail)

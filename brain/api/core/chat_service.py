"""Shared chat generation workflow for sync and streaming endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from config import get_settings
from core.agent_loop import AgentLoopResult, prepare_agent_reply, run_agent_loop
from core.llm_client import generate_chat_reply, stream_chat_reply
from core.pipeline import RouteDecision, route_message
from core.prompt_builder import build_chat_messages
from core.sse_events import (
    ContextEvent,
    DoneEvent,
    SessionEvent,
    SSEEvent,
    TokenEvent,
    ToolEvent,
)
from infra.learnings import capture_learnings_from_message, record_error_event
from memory.embedder import encode_text
from memory.memory import (
    append_session_message,
    archive_session_turn,
    get_or_create_session,
    list_session_messages,
)
from memory.memory_governance import maybe_run_memory_maintenance
from memory.retrieval import search_records
from protocol.message_envelope import MessageEnvelope, normalize_to_brain_message, serialize_context
from safety.guardrails import enforce_guardrails, enforce_session_limits


@dataclass(slots=True)
class GenerationContext:
    trace_id: str
    persona_id: str
    session_id: str
    route: RouteDecision
    user_message: str
    request_context: dict[str, Any]
    prompt_messages: list[dict[str, str]]
    knowledge_results: list[dict[str, Any]]
    memory_results: list[dict[str, Any]]


def prepare_generation(envelope: MessageEnvelope) -> GenerationContext:
    """Build prompt inputs and update the user side of the session."""
    cleaned_message = envelope.content.strip()
    cfg = get_settings()
    persona_id = envelope.context.persona_id

    if not cleaned_message:
        raise ValueError("message 不可為空")
    if len(cleaned_message) > cfg.max_input_length:
        raise ValueError(f"message 不可超過 {cfg.max_input_length} 字")
    enforce_guardrails("generate", cleaned_message, envelope.context)
    enforce_session_limits(envelope.context.session_id, persona_id)

    route = route_message(normalize_to_brain_message(envelope))
    session = get_or_create_session(envelope.context.session_id, persona_id)
    prior_messages = list_session_messages(session.session_id, persona_id)
    append_session_message(session.session_id, persona_id, "user", cleaned_message)

    knowledge_results, memory_results = _retrieve_rag_context(
        route, cleaned_message, persona_id, cfg,
    )
    request_ctx = serialize_context(envelope.context)
    prompt_messages = build_chat_messages(
        user_message=cleaned_message,
        request_context=request_ctx,
        session_messages=prior_messages,
        knowledge_results=knowledge_results,
        memory_results=memory_results,
    )

    return GenerationContext(
        trace_id=envelope.context.trace_id,
        persona_id=persona_id,
        session_id=session.session_id,
        route=route,
        user_message=cleaned_message,
        request_context=request_ctx,
        prompt_messages=prompt_messages,
        knowledge_results=knowledge_results,
        memory_results=memory_results,
    )


def _retrieve_rag_context(
    route: RouteDecision,
    message: str,
    persona_id: str,
    cfg: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch knowledge and memory results when RAG is enabled for this route."""
    if route.skip_rag:
        return [], []
    query_vector = encode_text(message)
    knowledge = search_records(
        "knowledge", query_vector, cfg.rag_top_k, persona_id=persona_id,
    )
    memory = search_records(
        "memories", query_vector, min(3, cfg.rag_top_k), persona_id=persona_id,
    )
    return knowledge, memory


def finalize_generation(context: GenerationContext, reply: str) -> dict[str, Any]:
    """Persist the assistant reply and return the standard API payload."""
    cleaned_reply = reply.strip()
    if not cleaned_reply:
        raise ValueError("LLM 沒有回傳內容")

    append_session_message(context.session_id, context.persona_id, "assistant", cleaned_reply)
    archive_session_turn(
        context.session_id,
        context.user_message,
        cleaned_reply,
        context.persona_id,
    )
    learnings_added = capture_learnings_from_message(context.user_message)
    maintenance = maybe_run_memory_maintenance()

    return {
        "status": "ok",
        "trace_id": context.trace_id,
        "session_id": context.session_id,
        "request_context": context.request_context,
        "reply": cleaned_reply,
        "knowledge_results": context.knowledge_results,
        "memory_results": context.memory_results,
        "history": list_session_messages(context.session_id, context.persona_id),
        "learnings_added": learnings_added,
        "memory_maintenance": maintenance,
    }


def execute_generation(context: GenerationContext) -> AgentLoopResult:
    """Run the configured agent loop on top of prepared prompt messages."""
    if context.route.skip_tools:
        return AgentLoopResult(
            reply=generate_chat_reply(context.prompt_messages),
            tool_steps=[],
        )
    return run_agent_loop(context.prompt_messages, persona_id=context.persona_id)


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
    yield ContextEvent(
        trace_id=context.trace_id,
        knowledge_count=len(context.knowledge_results),
        memory_count=len(context.memory_results),
        request_context=context.request_context,
    )

    reply_parts: list[str] = []
    tool_steps: list[dict[str, Any]] = []
    stream_messages: list[dict[str, Any]] = context.prompt_messages

    if not context.route.skip_tools:
        prepared = await asyncio.to_thread(
            prepare_agent_reply,
            context.prompt_messages,
            context.persona_id,
        )
        stream_messages = prepared.messages
        tool_steps = prepared.tool_steps
        for step in tool_steps:
            yield _tool_event_from_step(context.trace_id, step)

    async for token in stream_chat_reply(stream_messages):
        reply_parts.append(token)
        yield TokenEvent(trace_id=context.trace_id, token=token)

    full_reply = "".join(reply_parts)
    finalize_generation(context, full_reply)
    yield DoneEvent(
        trace_id=context.trace_id,
        session_id=context.session_id,
        reply=full_reply,
        knowledge_results=context.knowledge_results,
        memory_results=context.memory_results,
        tool_steps=tool_steps,
    )


def record_generation_failure(area: str, message: str, detail: str = "") -> None:
    """Store a summarized failure entry into ERRORS.md."""
    record_error_event(area=area, summary=message, detail=detail)

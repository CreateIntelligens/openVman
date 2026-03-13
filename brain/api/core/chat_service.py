"""Shared chat generation workflow for sync and streaming endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import get_settings
from core.agent_loop import AgentLoopResult, run_agent_loop
from core.prompt_builder import build_chat_messages
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
from protocol.message_envelope import MessageEnvelope, serialize_context
from safety.guardrails import enforce_guardrails


@dataclass(slots=True)
class GenerationContext:
    trace_id: str
    persona_id: str
    session_id: str
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

    session = get_or_create_session(envelope.context.session_id, persona_id)
    prior_messages = list_session_messages(session.session_id, persona_id)
    append_session_message(session.session_id, persona_id, "user", cleaned_message)

    query_vector = encode_text(cleaned_message)
    knowledge_results = search_records(
        "knowledge",
        query_vector,
        cfg.rag_top_k,
        persona_id=persona_id,
    )
    memory_results = search_records(
        "memories",
        query_vector,
        min(3, cfg.rag_top_k),
        persona_id=persona_id,
    )
    prompt_messages = build_chat_messages(
        user_message=cleaned_message,
        request_context=serialize_context(envelope.context),
        session_messages=prior_messages,
        knowledge_results=knowledge_results,
        memory_results=memory_results,
    )

    return GenerationContext(
        trace_id=envelope.context.trace_id,
        persona_id=persona_id,
        session_id=session.session_id,
        user_message=cleaned_message,
        request_context=serialize_context(envelope.context),
        prompt_messages=prompt_messages,
        knowledge_results=knowledge_results,
        memory_results=memory_results,
    )


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
    return run_agent_loop(context.prompt_messages, persona_id=context.persona_id)


def record_generation_failure(area: str, message: str, detail: str = "") -> None:
    """Store a summarized failure entry into ERRORS.md."""
    record_error_event(area=area, summary=message, detail=detail)

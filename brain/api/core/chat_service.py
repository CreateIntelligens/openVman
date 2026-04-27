"""Chat generation workflow."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from config import get_settings
from core.agent_loop import AgentLoopResult, ToolPhaseError, run_agent_loop  # noqa: F401 (ToolPhaseError re-exported)
from core.llm_client import LLMReply, generate_chat_turn
from core.pipeline import RouteDecision, route_message
from core.prompt_builder import build_chat_messages
from infra.learnings import record_error_event
from memory.memory import (
    append_session_message,
    archive_session_turn,
    get_or_create_session,
    list_session_messages,
)
from memory.memory_governance import maybe_run_memory_maintenance, write_summary_and_reindex
from protocol.message_envelope import (
    METADATA_ORIGINAL_USER_MESSAGE,
    MessageEnvelope,
    normalize_to_brain_message,
    read_text,
    serialize_context,
)
from safety.guardrails import enforce_guardrails, enforce_session_limits


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
    prior_messages: list[dict[str, Any]] = field(default_factory=list)
    forced_tool_name: str | None = None


def prepare_generation(envelope: MessageEnvelope) -> GenerationContext:
    """Build prompt inputs and update the user side of the session.

    Knowledge and memory retrieval is no longer done here — the LLM will
    call search_knowledge / search_memory tools during the agent loop.
    """
    cleaned_message = envelope.content.strip()
    stored_user_message = read_text(envelope.context.metadata, METADATA_ORIGINAL_USER_MESSAGE) or cleaned_message
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
    append_session_message(session.session_id, persona_id, "user", stored_user_message, project_id=project_id)

    request_ctx = serialize_context(envelope.context)
    prompt_messages = build_chat_messages(
        user_message=cleaned_message,
        request_context=request_ctx,
        session_messages=prior_messages,
        allow_tools=not route.skip_tools,
    )

    return GenerationContext(
        trace_id=envelope.context.trace_id,
        persona_id=persona_id,
        project_id=project_id,
        session_id=session.session_id,
        route=route,
        user_message=stored_user_message,
        request_context=request_ctx,
        prompt_messages=prompt_messages,
        prior_messages=prior_messages,
        forced_tool_name=route.forced_tool_name,
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
    write_summary_and_reindex(
        persona_id=context.persona_id,
        day=date.today().isoformat(),
        summary_text=f"User: {context.user_message}\nAssistant: {cleaned_reply}",
        source_turns=1,
        session_id=context.session_id,
        project_id=context.project_id,
    )

    # Memory is now written by the LLM via the save_memory tool —
    # no automatic per-turn memory write here.
    maintenance = maybe_run_memory_maintenance(project_id=context.project_id)

    history = [
        *context.prior_messages,
        {"role": "user", "content": context.user_message},
        {"role": "assistant", "content": cleaned_reply},
    ]
    return {
        "status": "ok",
        "trace_id": context.trace_id,
        "session_id": context.session_id,
        "request_context": context.request_context,
        "reply": cleaned_reply,
        "history": history,
        "memory_maintenance": maintenance,
    }


_TOOL_FALLBACK_HINT = (
    "[系統提示] 工具流程部分失敗。請優先使用已成功取得的工具資訊回答使用者，"
    "若資訊不足，請誠實說明限制並提供安全的下一步建議。"
)


def _inject_tool_fallback_hint(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a new message list with a system hint inserted before the last user message."""
    insert_idx = next(
        (i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"),
        len(messages),
    )
    return [*messages[:insert_idx], {"role": "system", "content": _TOOL_FALLBACK_HINT}, *messages[insert_idx:]]


def _supports_keyword_argument(func: Any, name: str) -> bool:
    try:
        params = inspect.signature(func).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(param.kind is inspect.Parameter.VAR_KEYWORD or param.name == name for param in params)


def _string_context_value(context: Any, name: str, default: str = "") -> str:
    value = getattr(context, name, default)
    return value if isinstance(value, str) else default


def _generate_turn_result(
    messages: list[dict[str, Any]],
    *,
    privacy_source: str,
    trace_id: str,
) -> LLMReply:
    kwargs: dict[str, Any] = {}
    if _supports_keyword_argument(generate_chat_turn, "privacy_source"):
        kwargs["privacy_source"] = privacy_source
    if trace_id and _supports_keyword_argument(generate_chat_turn, "trace_id"):
        kwargs["trace_id"] = trace_id
    return generate_chat_turn(messages, **kwargs)


def _reply_from_turn(turn: LLMReply) -> str:
    reply = turn.content.strip()
    if not reply:
        raise ValueError("LLM 沒有回傳內容")
    return reply


def execute_generation(context: GenerationContext) -> AgentLoopResult:
    """Run the configured agent loop on top of prepared prompt messages."""
    trace_id = _string_context_value(context, "trace_id")
    project_id = _string_context_value(context, "project_id", "default")

    if context.route.skip_tools:
        turn = _generate_turn_result(
            context.prompt_messages,
            privacy_source="chat",
            trace_id=trace_id,
        )
        return AgentLoopResult(
            reply=_reply_from_turn(turn),
            tool_steps=[],
            pii_report=turn.pii_report,
        )
    try:
        return run_agent_loop(
            context.prompt_messages,
            persona_id=context.persona_id,
            project_id=project_id,
            forced_tool_name=context.forced_tool_name,
        )
    except ToolPhaseError as exc:
        fallback = _inject_tool_fallback_hint(exc.partial_messages or context.prompt_messages)
        turn = _generate_turn_result(
            fallback,
            privacy_source="tool",
            trace_id=trace_id,
        )
        return AgentLoopResult(
            reply=_reply_from_turn(turn),
            tool_steps=exc.partial_steps,
            pii_report=turn.pii_report,
        )


def record_generation_failure(area: str, message: str, detail: str = "") -> None:
    """Store a summarized failure entry into ERRORS.md."""
    record_error_event(area=area, summary=message, detail=detail)
"""Chat generation workflow."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
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
    append_session_message_with_id,
    archive_session_turn,
    get_or_create_session,
    list_session_messages,
    update_session_message_metadata,
)
from memory.memory_governance import maybe_run_memory_maintenance, write_summary_and_reindex
from privacy.filter import PiiDetectionReport, detect_llm_messages_pii
from protocol.message_envelope import (
    METADATA_ORIGINAL_USER_MESSAGE,
    MessageEnvelope,
    normalize_to_brain_message,
    read_text,
    serialize_context,
)
from safety.guardrails import enforce_guardrails, enforce_session_limits

_pii_writeback_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pii-writeback")

logger = logging.getLogger(__name__)


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


def _serialize_history_message(msg: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {"role": msg["role"], "content": msg["content"]}
    msg_meta = msg.get("metadata") or {}
    if steps := msg_meta.get("tool_steps"):
        entry["tool_steps"] = steps
    if rts := msg_meta.get("response_time_s"):
        entry["response_time_s"] = rts
    if pw := msg_meta.get("privacy_warning"):
        entry["privacy_warning"] = pw
    return entry


def _pii_to_warning(report: PiiDetectionReport | None) -> dict[str, Any] | None:
    if report is None or not report.counts:
        return None
    return {"categories": list(report.categories), "counts": dict(report.counts)}


def _schedule_memory_writes(context: GenerationContext, cleaned_reply: str) -> None:
    """Run memory governance off the request hot path."""
    persona_id = context.persona_id
    project_id = context.project_id
    session_id = context.session_id
    user_message = context.user_message
    day = date.today().isoformat()
    summary_text = f"User: {user_message}\nAssistant: {cleaned_reply}"

    def _work() -> None:
        try:
            write_summary_and_reindex(
                persona_id=persona_id,
                day=day,
                summary_text=summary_text,
                source_turns=1,
                session_id=session_id,
                project_id=project_id,
            )
            maybe_run_memory_maintenance(project_id=project_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("background memory write failed project=%s: %s", project_id, exc)

    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _work)
    except RuntimeError:
        # No running loop (sync test path); execute inline.
        _work()


def _scan_reply_pii(reply: str, trace_id: str) -> dict[str, Any] | None:
    """Run OPF on a reply and return the warning dict (or None)."""
    try:
        report = detect_llm_messages_pii(
            [{"role": "user", "content": reply}],
            source="chat",
            trace_id=trace_id,
        )
        return _pii_to_warning(report)
    except Exception:
        logger.exception("[privacy] reply PII scan failed")
        return None


def _patch_reply_pii_metadata(
    future: Any, message_id: int, project_id: str,
) -> None:
    """Background task: wait for PII scan and write the warning to DB."""
    try:
        warning = future.result()
        if warning:
            update_session_message_metadata(
                message_id, {"privacy_warning": warning}, project_id=project_id,
            )
    except Exception:
        logger.exception("[privacy] reply PII writeback failed")


def finalize_generation(
    context: GenerationContext,
    reply: str,
    tool_steps: list[dict[str, Any]] | None = None,
    response_time_s: float | None = None,
) -> dict[str, Any]:
    """Persist the assistant reply and return the standard API payload.

    Memory governance (summary/reindex/maintenance) is dispatched to a background
    thread so it does not block the response.
    """
    cleaned_reply = reply.strip()
    if not cleaned_reply:
        raise ValueError("LLM 沒有回傳內容")

    # Run user + reply PII scans in the background so they don't block the response.
    user_pii_future = _pii_writeback_executor.submit(
        _scan_reply_pii, context.user_message, context.trace_id,
    )
    reply_pii_future = _pii_writeback_executor.submit(
        _scan_reply_pii, cleaned_reply, context.trace_id,
    )

    _, user_message_id = append_session_message_with_id(
        context.session_id, context.persona_id, "user", context.user_message,
        project_id=context.project_id,
    )
    _pii_writeback_executor.submit(
        _patch_reply_pii_metadata,
        user_pii_future, user_message_id, context.project_id,
    )

    meta: dict[str, Any] = {}
    if tool_steps:
        meta["tool_steps"] = tool_steps
    if response_time_s is not None:
        meta["response_time_s"] = response_time_s
    _, assistant_message_id = append_session_message_with_id(
        context.session_id, context.persona_id, "assistant", cleaned_reply,
        project_id=context.project_id, metadata=meta or None,
    )
    _pii_writeback_executor.submit(
        _patch_reply_pii_metadata,
        reply_pii_future, assistant_message_id, context.project_id,
    )
    archive_session_turn(
        context.session_id,
        context.user_message,
        cleaned_reply,
        context.persona_id,
        project_id=context.project_id,
    )
    _schedule_memory_writes(context, cleaned_reply)

    history = [_serialize_history_message(msg) for msg in context.prior_messages]
    user_entry: dict[str, Any] = {"role": "user", "content": context.user_message}
    # Opportunistic: include user/reply warnings if scans finished in time.
    pii_pending = False
    if user_pii_future.done():
        if (warning := user_pii_future.result()) is not None:
            user_entry["privacy_warning"] = warning
    else:
        pii_pending = True
    history.append(user_entry)
    assistant_entry: dict[str, Any] = {"role": "assistant", "content": cleaned_reply}
    if reply_pii_future.done():
        if (warning := reply_pii_future.result()) is not None:
            assistant_entry["privacy_warning"] = warning
    else:
        pii_pending = True
    if tool_steps:
        assistant_entry["tool_steps"] = tool_steps
    if response_time_s is not None:
        assistant_entry["response_time_s"] = response_time_s
    history.append(assistant_entry)
    return {
        "status": "ok",
        "trace_id": context.trace_id,
        "session_id": context.session_id,
        "request_context": context.request_context,
        "reply": cleaned_reply,
        "history": history,
        "pii_pending": pii_pending,
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


def _string_context_value(context: Any, name: str, default: str = "") -> str:
    value = getattr(context, name, default)
    return value if isinstance(value, str) else default


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
        turn = generate_chat_turn(
            context.prompt_messages,
            privacy_source="chat",
            trace_id=trace_id,
        )
        return AgentLoopResult(reply=_reply_from_turn(turn), tool_steps=[])
    try:
        return run_agent_loop(
            context.prompt_messages,
            persona_id=context.persona_id,
            project_id=project_id,
            forced_tool_name=context.forced_tool_name,
        )
    except ToolPhaseError as exc:
        fallback = _inject_tool_fallback_hint(exc.partial_messages or context.prompt_messages)
        turn = generate_chat_turn(
            fallback,
            privacy_source="tool",
            trace_id=trace_id,
        )
        return AgentLoopResult(reply=_reply_from_turn(turn), tool_steps=exc.partial_steps)


def record_generation_failure(area: str, message: str, detail: str = "") -> None:
    """Store a summarized failure entry into ERRORS.md."""
    record_error_event(area=area, summary=message, detail=detail)
"""Chat generation workflow."""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from config import get_settings
from core.agent_loop import (  # noqa: F401 (ToolPhaseError re-exported)
    AgentLoopResult,
    ToolPhaseError,
    run_agent_loop,
)
from core.generation_cancel import current_cancel_event
from core.llm_client import (
    LLMEmptyReplyError,
    LLMReply,
    TextDeltaListener,
    generate_chat_turn,
    stream_chat_turn,
)
from core.pipeline import RouteDecision, route_message
from core.prompt_builder import build_chat_messages
from core.turn_decisions import (
    TurnDecision,
    resolve_retrieval_language,
    run_turn_decision,
    turn_decision_config,
)
from core.reference_media import ReplyMediaChoice, choose_reference_media, earlier_pictures
from core.turn_reads import without_disabled_recall
from infra.learnings import record_error_event
from memory.memory import (
    append_session_message_with_id,
    archive_session_turn,
    get_or_create_session,
    list_session_messages,
    update_session_message_metadata,
)
from memory.memory_governance import (
    maybe_run_memory_maintenance,
    write_summary_and_reindex,
)
from privacy.filter import PiiDetectionReport, scan_text_for_pii
from protocol.message_envelope import (
    METADATA_ORIGINAL_USER_MESSAGE,
    MessageEnvelope,
    normalize_to_brain_message,
    read_text,
    serialize_context,
)
from safety.guardrails import enforce_guardrails, enforce_session_limits
from tools.context import (
    active_retrieval_language,
    active_speech_language,
    active_turn_decision_unavailable,
)
from tools.tool_registry import get_tool_registry

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
    reply_mode: str = ""
    turn_decision: TurnDecision | None = None
    input_language: str | None = None
    media_choice: ReplyMediaChoice | None = None
    preferred_language: str | None = None


def prepare_generation(
    envelope: MessageEnvelope, *, reply_mode: str = "", decision_debug: bool = False,
    preferred_language: str | None = None,
) -> GenerationContext:
    """Build prompt inputs and update the user side of the session.

    Knowledge and memory retrieval is no longer done here — the LLM will
    call search_knowledge / search_memory tools during the agent loop.

    *preferred_language* is the caller's language hint (``ChatRequest``): it replaces
    the project's primary language only where the message shows no language itself.
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

    # Decision policy is server-owned and bound to this finalized user turn.
    # Client metadata can provide ASR evidence, but cannot supply a policy.
    metadata = envelope.context.metadata
    eligible_turn = (
        envelope.context.message_type == "user"
        and not bool(metadata.get("ephemeral_user_message"))
        and not route.skip_tools
    )
    turn_decision: TurnDecision | None = None
    if eligible_turn:
        from knowledge.kb_settings import primary_language

        cfg = turn_decision_config(cfg)
        registered = {
            tool.get("function", {}).get("name")
            for tool in get_tool_registry().build_openai_tools()
        }
        turn_decision = run_turn_decision(
            user_text=stored_user_message,
            history=prior_messages,
            project_id=project_id,
            project_language=primary_language(project_id),
            speech_language=str(metadata.get("speech_language") or ""),
            available_tools=tuple(registered),
            config=cfg,
            turn_id=envelope.context.trace_id,
            # 用戶端斷線時連同進行中的決策請求一起停，不等它跑完。
            cancel_event=current_cancel_event(),
            capture_debug=decision_debug,
            preferred_language=preferred_language or "",
        )
        turn_decision = without_disabled_recall(turn_decision, session.session_id, project_id)

    request_ctx = serialize_context(envelope.context)
    input_language = None
    if turn_decision is not None:
        from knowledge.kb_settings import primary_language
        from memory.language_detect import detect_language

        speech_language = str(metadata.get("speech_language") or "")
        supported = {"zh", "en", "es", "nan", "ja", "ko"}
        input_language = (
            speech_language if speech_language in supported else
            turn_decision.policy.dominant_language
            if turn_decision.policy.dominant_language in supported else
            detect_language(
                stored_user_message, preferred_language or primary_language(project_id),
            )
        )
    prompt_messages = build_chat_messages(
        user_message=cleaned_message,
        request_context=request_ctx,
        session_messages=prior_messages,
        allow_tools=not route.skip_tools,
        turn_policy=turn_decision.policy if turn_decision else None,
        decision_dependency_unavailable=bool(
            turn_decision and turn_decision.dependency_unavailable
        ),
        preferred_language=preferred_language,
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
        reply_mode=reply_mode,
        turn_decision=turn_decision,
        input_language=input_language,
        preferred_language=preferred_language,
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
    if citations := msg_meta.get("citations"):
        entry["citations"] = citations
    if image_id := msg_meta.get("image_id"):
        entry["image_id"] = image_id
    if url := msg_meta.get("url"):
        entry["url"] = url
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


def _scan_user_pii(message: str, trace_id: str) -> dict[str, Any] | None:
    """Ask Clef about personal data in the user's message; None when none or skipped."""
    try:
        return _pii_to_warning(scan_text_for_pii(message, trace_id=trace_id))
    except Exception:
        logger.exception("[privacy] user PII scan failed")
        return None


def _patch_message_pii_metadata(
    future: Any, message_id: int, project_id: str,
) -> None:
    """Background task: wait for the PII scan and write the warning to the message."""
    try:
        warning = future.result()
        if warning:
            update_session_message_metadata(
                message_id, {"privacy_warning": warning}, project_id=project_id,
            )
    except Exception:
        logger.exception("[privacy] reply PII writeback failed")


def _step_citations(step: Any) -> list[tuple[str, dict[str, Any]]]:
    """``(uri, citation)`` pairs one tool step returned; empty for errors and non-search tools."""
    result = step.get("result") if isinstance(step, dict) else None
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            return []
    if not isinstance(result, dict):
        return []
    data = result.get("data")
    citation_source = data if isinstance(data, dict) else result
    pairs: list[tuple[str, dict[str, Any]]] = []
    for cite in citation_source.get("citations") or []:
        if not isinstance(cite, dict):
            continue
        uri = str(cite.get("uri") or cite.get("title") or "")
        if uri:
            pairs.append((uri, cite))
    return pairs


def _collect_citations_from_tool_steps(tool_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate ``citations`` across all search-tool steps, dedupe, sort by distance."""
    by_uri: dict[str, dict[str, Any]] = {}
    for step in tool_steps:
        for uri, cite in _step_citations(step):
            distance = float(cite.get("distance", 999.0))
            existing = by_uri.get(uri)
            if existing is None or distance < float(existing.get("distance", 999.0)):
                by_uri[uri] = dict(cite)
    return sorted(by_uri.values(), key=lambda c: float(c.get("distance", 999.0)))


_KNOWLEDGE_SEARCH_TOOL = "search_knowledge"


_NO_ANSWER_QUESTION = {
    "reply_says_no_answer": {
        "type": "noul",
        "instructions": "助理這段回覆，是不是在說資料裡找不到、沒有提到，或無法回答使用者的問題？",
        "criteria": {
            "true": "回覆表示查不到、資料沒有提到、無法確認或請使用者改問其他窗口，沒有給出實際答案",
            "false": "回覆給出了實際的答案或資訊，即使只是部分回答",
        },
    },
}


def _reply_says_no_answer(question: str, reply: str) -> bool | None:
    """Ask the decision chain whether the reply admits the material has no answer.

    知識庫檢索門檻刻意放寬（接住錯字、跨語言），沾邊卻沒有答案的問題也會帶回段落：
    2026-10-14 醫院專案問「火星上有幾座醫院？」檢索到院內服務的 QA、回答說資料中
    沒有提到，引用卻有，no_answer 是 false。相似度門檻切不乾淨（相關最低 0.711、
    無關最高 0.719），改看回覆本身。None 表示沒判斷（關閉、逾時、失敗）。
    """
    cfg = get_settings()
    if not cfg.no_answer_judge_enabled or not reply.strip():
        return None
    try:
        from core.decision_router import decide_noul

        probability = decide_noul(
            {"user_question": question, "assistant_reply": reply},
            _NO_ANSWER_QUESTION["reply_says_no_answer"],
            timeout=cfg.no_answer_judge_timeout_seconds,
            purpose="no_answer",
        )
    except Exception as exc:  # noqa: BLE001 - 判斷失敗就照引用規則，不影響回答
        logger.warning("no_answer judge failed: %s", exc)
        return None
    return probability >= 0.5


def answer_source_fields(
    tool_steps: list[dict[str, Any]],
    project_id: str,
    *,
    question: str = "",
    reply: str = "",
) -> dict[str, Any]:
    """Say whether this turn's answer came from the knowledge base, for integrators.

    只看 search_knowledge 的引用：網路、記憶的引用不是知識庫命中。整合方拿
    ``no_answer`` 決定要不要把回答換成固定的拒答句。有引用時再問決策鏈回覆是否
    其實在說查不到；判斷不了就只看引用。
    """
    knowledge_steps = [
        step for step in tool_steps
        if isinstance(step, dict) and step.get("name") == _KNOWLEDGE_SEARCH_TOOL
    ]
    uris = {uri for step in knowledge_steps for uri, _ in _step_citations(step)}
    if not uris:
        source = "none"
    else:
        from knowledge.doc_meta import load_doc_meta

        meta = load_doc_meta(project_id)
        source = "qa" if any(
            meta.get(uri, {}).get("source_type") == "qa" for uri in uris
        ) else "knowledge"
    searched = bool(knowledge_steps)
    no_answer = searched and not uris
    if searched and uris and _reply_says_no_answer(question, reply):
        no_answer = True
    return {
        "answer_source": source,
        "knowledge_searched": searched,
        "no_answer": no_answer,
    }


def reply_media(context: GenerationContext, tool_steps: list[dict[str, Any]]) -> dict[str, str] | None:
    """The picture this turn should show; None keeps the closest citation's picture."""
    if context.media_choice is not None:
        return context.media_choice.result(tool_steps)
    return choose_reference_media(context.user_message, tool_steps)


def _primary_media(citations: list[dict[str, Any]]) -> dict[str, str]:
    """Project the first citation's media into the JTAI-compatible envelope."""
    if not citations:
        return {}

    primary = citations[0]
    media: dict[str, str] = {}
    image_id = str(primary.get("image_id") or primary.get("image") or "").strip()
    url = str(primary.get("url") or primary.get("source_url") or "").strip()
    if image_id:
        media["image_id"] = image_id
    if url:
        media["url"] = url
    return media


def finalize_generation(
    context: GenerationContext,
    reply: str,
    tool_steps: list[dict[str, Any]] | None = None,
    response_time_s: float | None = None,
    *,
    persist: bool = True,
    persisted_message_ids: tuple[int, int] | None = None,
    media: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Persist the assistant reply and return the standard API payload.

    *media* is the picture the decision chain chose (``{}`` for none); None keeps the
    closest citation's picture. Callers decide once per turn with ``reply_media`` so an
    accepted replaceable turn shows the same picture it was staged with.

    Memory governance (summary/reindex/maintenance) is dispatched to a background
    thread so it does not block the response.

    Replaceable HTTP turns use ``persist=False`` until delivery is acknowledged;
    ``persisted_message_ids`` reuses the pair written by the atomic acknowledgement.
    """
    cleaned_reply = reply.strip()
    if not cleaned_reply:
        raise LLMEmptyReplyError("LLM 沒有回傳內容")

    ephemeral_user = bool(
        context.request_context.get("metadata", {}).get("ephemeral_user_message")
    )

    if persist and not ephemeral_user:
        # 只掃使用者的話：回覆的內容來自知識庫與模型，不是訪客交出來的個資。
        user_pii_future = _pii_writeback_executor.submit(
            _scan_user_pii, context.user_message, context.trace_id,
        )
        # 前台語音經 ASR 時會帶 speech_language（例如聽出是台語），轉錄文字看不出來。
        speech_language = context.request_context.get("metadata", {}).get("speech_language")
        input_language = (
            context.turn_decision.policy.dominant_language
            if context.turn_decision is not None
            else None
        )
        if persisted_message_ids is not None:
            user_message_id = persisted_message_ids[0]
        else:
            _, user_message_id = append_session_message_with_id(
                context.session_id, context.persona_id,
                "user", context.user_message,
                project_id=context.project_id,
                language=context.input_language or (
                    speech_language if isinstance(speech_language, str) else None
                ),
            )
        _pii_writeback_executor.submit(
            _patch_message_pii_metadata,
            user_pii_future, user_message_id, context.project_id,
        )
    else:
        user_pii_future = None

    citations = _collect_citations_from_tool_steps(tool_steps or [])
    if media is None:
        primary_media = _primary_media(citations)
    else:
        # 前台沒拿到 image_id 會退回第一筆引用的圖，所以選了別張或不顯示時要一起拿掉。
        citations = [
            {key: value for key, value in cite.items() if key not in ("image_id", "image")}
            for cite in citations
        ]
        primary_media = dict(media)
    meta: dict[str, Any] = {}
    if tool_steps:
        meta["tool_steps"] = tool_steps
    if response_time_s is not None:
        meta["response_time_s"] = response_time_s
    if citations:
        meta["citations"] = citations
    meta.update(primary_media)
    if persist and persisted_message_ids is None:
        append_session_message_with_id(
            context.session_id, context.persona_id,
            "assistant", cleaned_reply,
            project_id=context.project_id, metadata=meta or None,
        )
    if persist and not ephemeral_user:
        archive_session_turn(
            context.session_id,
            context.user_message,
            cleaned_reply,
            context.persona_id,
            project_id=context.project_id,
        )
    if persist:
        _schedule_memory_writes(context, cleaned_reply)

    history = [_serialize_history_message(msg) for msg in context.prior_messages]
    user_entry: dict[str, Any] = {"role": "user", "content": context.user_message}
    # Opportunistic: include the user warning if the scan finished in time.
    pii_pending = False
    if user_pii_future is not None and user_pii_future.done():
        if (warning := user_pii_future.result()) is not None:
            user_entry["privacy_warning"] = warning
    elif user_pii_future is not None:
        pii_pending = True
    history.append(user_entry)
    assistant_entry: dict[str, Any] = {"role": "assistant", "content": cleaned_reply}
    if tool_steps:
        assistant_entry["tool_steps"] = tool_steps
    if response_time_s is not None:
        assistant_entry["response_time_s"] = response_time_s
    if citations:
        assistant_entry["citations"] = citations
    assistant_entry.update(primary_media)
    history.append(assistant_entry)
    response = {
        "status": "ok",
        "trace_id": context.trace_id,
        "session_id": context.session_id,
        "request_context": context.request_context,
        "reply": cleaned_reply,
        "history": history,
        "pii_pending": pii_pending,
        "citations": citations,
        **answer_source_fields(
            tool_steps or [], context.project_id,
            question=context.user_message, reply=cleaned_reply,
        ),
    }
    response.update(primary_media)
    return response


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
        raise LLMEmptyReplyError("LLM 沒有回傳內容")
    return reply


def _single_turn(
    messages: list[dict[str, Any]], trace_id: str, text_listener: TextDeltaListener | None,
) -> LLMReply:
    if text_listener is None:
        return generate_chat_turn(messages, trace_id=trace_id)
    return stream_chat_turn(messages, trace_id=trace_id, text_listener=text_listener)


def execute_generation(
    context: GenerationContext, *, text_listener: TextDeltaListener | None = None,
) -> AgentLoopResult:
    """Run the configured agent loop on top of prepared prompt messages.

    *text_listener* gets the answer's text deltas while the model writes it
    (``/brain/chat/stream``); without it every turn behaves exactly as before.
    """
    trace_id = _string_context_value(context, "trace_id")
    project_id = _string_context_value(context, "project_id", "default")

    if context.route.skip_tools:
        turn = _single_turn(context.prompt_messages, trace_id, text_listener)
        return AgentLoopResult(reply=_reply_from_turn(turn), tool_steps=[])
    speech_language = context.request_context.get("metadata", {}).get("speech_language")
    speech_token = active_speech_language.set(
        speech_language if isinstance(speech_language, str) else "",
    )
    if context.turn_decision is not None:
        retrieval_language = context.turn_decision.policy.retrieval_language
    elif context.preferred_language:
        # 沒跑當輪決策（視覺事件）時也要照整合方帶的語言提示查，跟有決策時一致。
        from knowledge.kb_settings import primary_language

        retrieval_language = resolve_retrieval_language(
            user_text=context.user_message,
            project_language=primary_language(context.project_id),
            speech_language=speech_language if isinstance(speech_language, str) else "",
            preferred_language=context.preferred_language,
        )
    else:
        retrieval_language = ""
    retrieval_token = active_retrieval_language.set(retrieval_language or "")
    unavailable_token = active_turn_decision_unavailable.set(bool(
        context.turn_decision and context.turn_decision.dependency_unavailable
    ))
    wants_previous_picture = bool(
        context.turn_decision and context.turn_decision.policy.wants_previous_picture,
    )
    context.media_choice = ReplyMediaChoice(
        context.user_message,
        earlier=earlier_pictures(context.prior_messages) if wants_previous_picture else None,
    )
    try:
        return run_agent_loop(
            context.prompt_messages,
            persona_id=context.persona_id,
            project_id=project_id,
            forced_tool_name=context.forced_tool_name,
            # 只有一般使用者回合才強制先查知識庫：slash command 已指定工具，
            # role=tool 的訊息雖然 path 也是 "tool" 但 skip_rag=True，都不該強制。
            allow_forced_knowledge_search=(
                not context.route.skip_rag and not context.forced_tool_name
                and not (
                    context.turn_decision is not None
                    and context.turn_decision.policy.force_knowledge_search is False
                )
            ),
            reply_mode=context.reply_mode,
            force_web_search=bool(
                context.turn_decision
                and context.turn_decision.policy.needs_web is True
            ),
            force_memory_search=bool(
                context.turn_decision
                and context.turn_decision.policy.needs_memory is True
            ),
            force_knowledge_search=bool(
                context.turn_decision
                and context.turn_decision.policy.needs_knowledge is True
            ),
            on_tool_round=context.media_choice.on_tool_round,
            **({"text_listener": text_listener} if text_listener is not None else {}),
        )
    except ToolPhaseError as exc:
        fallback = _inject_tool_fallback_hint(exc.partial_messages or context.prompt_messages)
        turn = _single_turn(fallback, trace_id, text_listener)
        return AgentLoopResult(reply=_reply_from_turn(turn), tool_steps=exc.partial_steps)
    finally:
        active_speech_language.reset(speech_token)
        active_retrieval_language.reset(retrieval_token)
        active_turn_decision_unavailable.reset(unavailable_token)


def record_generation_failure(area: str, message: str, detail: str = "") -> None:
    """Store a summarized failure entry into ERRORS.md."""
    record_error_event(area=area, summary=message, detail=detail)

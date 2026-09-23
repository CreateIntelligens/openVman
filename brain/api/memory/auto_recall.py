"""Active memory recall — auto-inject relevant memories into system prompt."""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from time import monotonic
from typing import Any

from config import get_settings

logger = logging.getLogger(__name__)

# Sentinel used to mark/strip injected recall blocks
_RECALL_TAG = "<!-- ACTIVE_RECALL_TAG -->"

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="recall")


# ------------------------------------------------------------------
# 3.1 RecallResult dataclass
# ------------------------------------------------------------------

@dataclass(slots=True)
class RecallResult:
    """Outcome of an auto recall attempt."""

    summary: str
    status: str  # "ok" | "empty" | "timeout" | "error" | "cache_hit" | "disabled"
    source: str  # "llm" | "formatted" | "cache" | "none"
    elapsed_ms: float


# ------------------------------------------------------------------
# 3.2 Query construction
# ------------------------------------------------------------------

def build_recall_query(
    messages: list[dict[str, Any]],
    user_message: str,
    mode: str,
    config: Any,
) -> str:
    """Build the search query string from session context."""
    user_message = user_message.strip()

    if mode == "message":
        return user_message

    if mode == "recent":
        max_turns = config.auto_recall_recent_user_turns
        max_chars = config.auto_recall_recent_user_chars
        parts: list[str] = []
        for msg in reversed(messages):
            if str(msg.get("role", "")) == "user":
                content = strip_recall_noise(str(msg.get("content", "")))
                if content:
                    parts.append(content[:max_chars])
                if len(parts) >= max_turns:
                    break
        parts.reverse()
        if user_message:
            parts.append(user_message)
        return "\n".join(parts)

    # mode == "full"
    parts = [
        strip_recall_noise(str(msg.get("content", "")))
        for msg in messages
        if strip_recall_noise(str(msg.get("content", "")))
    ]
    if user_message:
        parts.append(user_message)
    return "\n".join(parts)


# ------------------------------------------------------------------
# 3.3 Noise stripping
# ------------------------------------------------------------------

def strip_recall_noise(text: str) -> str:
    """Remove ``<!-- ACTIVE_RECALL_TAG -->`` and the ``ACTIVE_RECALL_CONTEXT`` block."""
    if _RECALL_TAG not in text:
        return text
    # Remove everything from the tag to the next blank-line boundary
    cleaned = re.sub(
        re.escape(_RECALL_TAG) + r"[\s\S]*?(?=\n\n|\Z)",
        "",
        text,
    )
    return cleaned.strip()


# ------------------------------------------------------------------
# 3.4 Format recall results (fallback when LLM summarizer is off)
# ------------------------------------------------------------------

def _format_recall_results(results: list[dict[str, Any]]) -> str:
    """Format retrieved memory records into a plain-text list."""
    return "\n".join(
        f"{i}. {str(record.get('text', '')).strip()}"
        for i, record in enumerate(results, 1)
        if str(record.get("text", "")).strip()
    )


def _truncate_text(text: str, max_chars: int) -> str:
    """Truncate text to max_chars at the last word boundary."""
    if not text or len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(" ", 1)[0]
    return truncated + "…"


# ------------------------------------------------------------------
# 3.5 LLM summarizer
# ------------------------------------------------------------------

_SUMMARIZER_SYSTEM_PROMPT = (
    "你是記憶摘要助手。根據以下搜尋結果，生成一段簡潔的背景提示，"
    "讓主對話 AI 在回答時擁有相關歷史上下文。\n"
    "規則：\n"
    "- 只保留與當前查詢相關的記憶\n"
    "- 用自然語言、第三人稱描述（例如「使用者曾提到…」）\n"
    "- 如果搜尋結果完全無關，只回覆 NONE\n"
    "- 不要編造不存在的資訊\n"
    "- 回覆純文字，不使用 markdown"
)


def _llm_summarize(query: str, results: list[dict[str, Any]], config: Any) -> str:
    """Call a lightweight LLM to produce a semantic summary of recall results."""
    from core.llm_client import generate_chat_reply

    memory_text = _format_recall_results(results)
    if not memory_text:
        return ""

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SUMMARIZER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"查詢：{query}\n\n記憶搜尋結果：\n{memory_text}",
        },
    ]
    summary = generate_chat_reply(
        messages,
        model_override=(config.auto_recall_llm_model or None),
        privacy_source="auto_recall",
    ).strip()

    # LLM returns "NONE" when results are irrelevant
    if summary.upper() == "NONE":
        return ""

    return _truncate_text(summary, config.auto_recall_max_summary_chars)


def _jev_filter(query: str, results: list[dict[str, Any]], config: Any) -> list[dict[str, Any]]:
    """Keep only memories Jev judges relevant to the query (one call, one question each).

    取代 LLM 摘要的「相關／NONE」判斷，每輪省一次 LLM 呼叫；不再改寫成摘要，
    命中的記憶原文條列給主對話。會把記憶原文送到 Jev（2026-09-23 使用者同意）。
    """
    from core.jev_client import jev_nouls

    memories = [
        (f"m{i}", text, record)
        for i, record in enumerate(results, 1)
        if (text := str(record.get("text", "")).strip())
    ]
    if not memories:
        return []
    state = json.dumps(
        {"query": query, "memories": [{"id": key, "text": text} for key, text, _ in memories]},
        ensure_ascii=False,
    )
    questions = {
        key: {
            "instructions": f"記憶 {key} 是否與使用者這句話（query）相關，提供給助理能幫助回答或延續對話？",
            "criteria": {
                "true": "記憶內容和 query 的主題、人物、偏好或需求直接相關",
                "false": "記憶和 query 無關，只是剛好字面相近",
            },
        }
        for key, _, _ in memories
    }
    scores = jev_nouls(state, questions, timeout=config.jev_gate_timeout_seconds)
    kept = {key for key, score in scores.items() if score >= 0.5}
    logger.info(json.dumps(
        {"event": "auto_recall_jev", "candidates": len(memories), "kept": len(kept)},
    ))
    return [record for key, _, record in memories if key in kept]


# ------------------------------------------------------------------
# 3.6 Core recall execution
# ------------------------------------------------------------------

def _run_recall(
    query: str,
    persona_id: str,
    project_id: str,
    config: Any,
) -> RecallResult:
    """Execute vector search on memories table and optionally summarize."""
    from core.retrieval_service import retrieve_context

    start = monotonic()

    bundle = retrieve_context(
        query=query,
        persona_id=persona_id,
        project_id=project_id,
    )
    memory_results = bundle.memory_results

    if not memory_results:
        return RecallResult(
            summary="",
            status="empty",
            source="none",
            elapsed_ms=(monotonic() - start) * 1000,
        )

    from core.jev_client import jev_available

    summary = None
    source = "none"
    if getattr(config, "auto_recall_use_jev_filter", False) and jev_available():
        try:
            relevant = _jev_filter(query, memory_results, config)
            summary = _truncate_text(
                _format_recall_results(relevant), config.auto_recall_max_summary_chars,
            )
            source = "jev"
        except Exception as exc:
            # 例外可能夾帶回應內容，只記型別；退回原本的 LLM 摘要。
            logger.warning(json.dumps(
                {"event": "auto_recall_jev_fallback", "error_type": type(exc).__name__},
            ))
    if summary is None and config.auto_recall_use_llm_summarizer:
        summary = _llm_summarize(query, memory_results, config)
        source = "llm"
    elif summary is None:
        summary = _truncate_text(
            _format_recall_results(memory_results),
            config.auto_recall_max_summary_chars,
        )
        source = "formatted"

    return RecallResult(
        summary=summary,
        status="ok" if summary else "empty",
        source=source,
        elapsed_ms=(monotonic() - start) * 1000,
    )


# ------------------------------------------------------------------
# 3.7 Public entry point
# ------------------------------------------------------------------

def run_auto_recall(
    session_messages: list[dict[str, Any]],
    user_message: str,
    persona_id: str,
    project_id: str,
    *,
    session_id: str = "",
) -> RecallResult:
    """Top-level auto recall: cache check → search → summarize → cache store."""
    start = monotonic()

    def _make_result(summary: str = "", status: str = "ok", source: str = "none") -> RecallResult:
        return RecallResult(
            summary=summary,
            status=status,
            source=source,
            elapsed_ms=(monotonic() - start) * 1000,
        )

    try:
        config = get_settings()
        if not config.auto_recall_enabled:
            return _make_result(status="disabled")

        query = build_recall_query(
            session_messages, user_message, config.auto_recall_query_mode, config,
        )
        if not query.strip():
            return _make_result(status="empty")

        from memory.recall_cache import get_recall_cache, make_cache_key

        cache = get_recall_cache()
        cache_key = make_cache_key(session_id or f"{persona_id}:{project_id}", query)
        cached = cache.get(cache_key)
        if cached is not None:
            return _make_result(summary=cached, status="cache_hit", source="cache")

        # Execute with timeout
        timeout_s = config.auto_recall_timeout_ms / 1000.0
        future = _executor.submit(_run_recall, query, persona_id, project_id, config)
        try:
            result = future.result(timeout=timeout_s)
        except TimeoutError:
            future.cancel()
            logger.warning("auto_recall timeout after %.0fms", timeout_s * 1000)
            return _make_result(status="timeout")

        # Cache on success
        if result.status in ("ok", "empty"):
            cache.set(cache_key, result.summary)

        result.elapsed_ms = (monotonic() - start) * 1000
        return result

    except Exception:
        logger.exception("auto_recall failed, degrading to empty")
        return _make_result(status="error")

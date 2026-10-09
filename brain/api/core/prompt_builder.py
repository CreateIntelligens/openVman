"""Prompt assembly for the chat generation flow."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger("brain")

from config import get_settings
from core.asr_glossary import glossary_line
from core.pipeline import enforce_context_budget
from infra.reflection import (
    compress_text,
    select_recent_messages,
    summarize_message_history,
)
from knowledge.workspace import load_core_workspace_context
from tools.builtin.product_tools import product_prompt_line
from .prompt_templates import (
    DEFAULT_ANSWER_RULES,
    DEFAULT_TOOL_INSTRUCTIONS,
    NO_TOOLS_ANSWER_RULES,
    NO_TOOLS_INSTRUCTIONS,
    reply_language_line,
)
from .turn_decisions import TurnPolicy


# Workspace blocks injected into the system prompt, ordered by priority.
# Each entry: (label used in prompt, config attribute for char budget).
_WORKSPACE_BLOCK_CONFIG: list[tuple[str, str]] = [
    ("IDENTITY",  "prompt_identity_char_budget"),
    ("SOUL",      "prompt_soul_char_budget"),
    ("MEMORY",    "prompt_memory_char_budget"),
    ("AGENTS",    "prompt_agents_char_budget"),
    ("TOOLS",     "prompt_tools_char_budget"),
    ("LEARNINGS", "prompt_learnings_char_budget"),
    ("ERRORS",    "prompt_errors_char_budget"),
]


def _speech_language(request_context: dict[str, Any]) -> str:
    metadata = request_context.get("metadata")
    value = metadata.get("speech_language") if isinstance(metadata, dict) else ""
    return value if isinstance(value, str) else ""


def build_chat_messages(
    user_message: str,
    request_context: dict[str, Any],
    session_messages: list[dict[str, Any]],
    *,
    allow_tools: bool = True,
    turn_policy: TurnPolicy | None = None,
    decision_dependency_unavailable: bool = False,
) -> list[dict[str, str]]:
    """Build the system and conversation messages for the LLM call.

    Knowledge and memory retrieval are handled by tool calls (search_knowledge,
    search_memory) during the agent loop — they are NOT injected into the prompt.
    """
    cfg = get_settings()
    persona_id = str(request_context.get("persona_id", "default"))
    project_id = str(request_context.get("project_id", "default"))
    session_id = str(request_context.get("session_id", ""))

    workspace = load_core_workspace_context(
        persona_id,
        project_id=project_id,
    )
    history_summary = summarize_message_history(session_messages)
    workspace_blocks = [
        _format_workspace_block(label, workspace[label.lower()], getattr(cfg, budget_attr))
        for label, budget_attr in _WORKSPACE_BLOCK_CONFIG
    ]

    recall_block = _build_recall_block(
        cfg=cfg,
        session_messages=session_messages,
        user_message=user_message,
        persona_id=persona_id,
        project_id=project_id,
        session_id=session_id,
        enabled_by_policy=turn_policy.auto_recall is not False if turn_policy else True,
        skip_jev_filter=decision_dependency_unavailable,
    )
    tool_instructions = DEFAULT_TOOL_INSTRUCTIONS if allow_tools else NO_TOOLS_INSTRUCTIONS
    answer_rules = DEFAULT_ANSWER_RULES if allow_tools else NO_TOOLS_ANSWER_RULES
    if allow_tools and turn_policy is not None:
        tool_instructions, answer_rules = _apply_retrieval_policy_to_instructions(
            tool_instructions, answer_rules, turn_policy,
        )

    # 固定的在前、每輪會變的在後：Gemini 隱式快取只認完全相同的開頭。原本 REQUEST
    # CONTEXT（trace_id、精確到秒的時間）夾在人設與回答規則中間、自動回憶插在人設
    # 前面，近 3 天只有 25% 輸入 tokens 命中快取。
    system_prompt = "\n\n".join(

        block
        for block in [
            "你是 `openVman Brain` 的對話核心。回答時要遵守以下上下文，且不要編造不存在的資訊。",
            tool_instructions,
            product_prompt_line(project_id) if allow_tools else "",
            *workspace_blocks,
            answer_rules,
            glossary_line(project_id),
            recall_block,
            _format_request_context(request_context),
            history_summary,
            reply_language_line(
                project_id, user_message, _speech_language(request_context),
                resolved_language=turn_policy.response_language if turn_policy else None,
            ),
            _tone_delivery_line(turn_policy.tone if turn_policy else None),
            _turn_retrieval_line(turn_policy),
        ]
        if block
    )
    system_prompt = compress_text(system_prompt, cfg.prompt_system_char_budget)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(select_recent_messages(session_messages))
    messages.append({"role": "user", "content": user_message})
    return enforce_context_budget(
        messages,
        total_char_budget=cfg.prompt_total_char_budget,
    )


def _format_recall_block(result: Any) -> str:
    """Format a RecallResult into a tagged workspace block."""
    if not result.summary:
        return ""
    return f"<!-- ACTIVE_RECALL_TAG -->\nACTIVE_RECALL_CONTEXT：\n{result.summary}"


def _build_recall_block(
    *,
    cfg: Any,
    session_messages: list[dict[str, Any]],
    user_message: str,
    persona_id: str,
    project_id: str,
    session_id: str,
    enabled_by_policy: bool = True,
    skip_jev_filter: bool = False,
) -> str:
    """Return the formatted auto-recall block, degrading silently on failure."""
    if not enabled_by_policy or not cfg.auto_recall_enabled:
        return ""
    if _is_session_recall_disabled(session_id=session_id, project_id=project_id):
        return ""

    try:
        from memory.auto_recall import run_auto_recall

        result = run_auto_recall(
            session_messages,
            user_message,
            persona_id,
            project_id,
            session_id=session_id,
            skip_jev_filter=skip_jev_filter,
        )
    except Exception:
        logger.warning("auto_recall failed, skipping recall block", exc_info=True)
        return ""

    return _format_recall_block(result)


def _tone_delivery_line(tone: str | None) -> str:
    lines = {
        "confused": "當輪語氣提示：使用清楚、分步的說明；先回答核心問題，再補必要背景。",
        "frustrated": "當輪語氣提示：簡潔承認使用者的困擾，直接處理問題與下一步；避免辯解或揣測情緒。",
        "urgent": "當輪語氣提示：先給可立即採取的答案或步驟，再補充限制。",
        "lighthearted": "當輪語氣提示：可自然輕鬆地回應，仍保持資訊準確。",
    }
    return lines.get(tone or "", "")


def _turn_retrieval_line(policy: TurnPolicy | None) -> str:
    if policy is None:
        return ""
    lines = []
    if policy.needs_knowledge is False:
        lines.append("當輪分類判定目前問題不需要專案知識；可直接回答，若回答過程發現需要專案事實仍可使用 search_knowledge。")
    elif policy.needs_knowledge is True:
        lines.append("當輪需要專案知識，請先使用 search_knowledge。")
    if policy.needs_web is True:
        lines.append("當輪需要公開或即時資訊，請使用 search_web。")
    if policy.needs_memory is True:
        lines.append("當輪需要過去對話或個人偏好時，請使用 search_memory。")
    return "當輪檢索提示：" + "".join(lines) if lines else ""


def _apply_retrieval_policy_to_instructions(
    tool_instructions: str,
    answer_rules: str,
    policy: TurnPolicy,
) -> tuple[str, str]:
    if policy.needs_knowledge is False:
        tool_instructions = tool_instructions.replace(
            "**必須先呼叫此工具再回答**",
            "若回答需要專案事實才呼叫此工具",
        ).replace(
            "search_knowledge 一定要叫；",
            "search_knowledge 依本輪分類與回答需要呼叫；",
        )
        answer_rules = answer_rules.replace(
            "**先呼叫 search_knowledge / search_memory 再回答**",
            "需要相應資料時先呼叫 search_knowledge / search_memory 再回答",
        )
    if policy.needs_memory is False:
        tool_instructions = tool_instructions.replace(
            "當使用者提到過去對話、偏好或可能曾經告訴過你的個人資訊時主動呼叫",
            "只有本輪分類為需要過去對話或回答缺少必要個人資訊時才呼叫",
        )
    if policy.needs_web is False:
        tool_instructions = tool_instructions.replace(
            "最新資訊、新聞、天氣、店家地點或其他公開資料必須搜尋。",
            "只有回答需要最新資訊、新聞、天氣、店家地點或其他公開資料時才搜尋。",
        )
        answer_rules = answer_rules.replace(
            "涉及即時或公開網路資訊（包含新聞、天氣）時，使用 search_web；",
            "回答需要即時或公開網路資訊（包含新聞、天氣）時，使用 search_web；",
        )
    return tool_instructions, answer_rules


def _is_session_recall_disabled(*, session_id: str, project_id: str) -> bool:
    """Best-effort per-session recall toggle lookup."""
    if not session_id:
        return False

    try:
        from memory.memory import is_session_recall_disabled

        return is_session_recall_disabled(session_id, project_id)
    except Exception:
        return False


def _format_workspace_block(label: str, content: str, max_chars: int) -> str:
    compressed = compress_text(content, max_chars)
    return f"{label}：\n{compressed}" if compressed else ""


def _format_request_context(request_context: dict[str, Any]) -> str:
    now = datetime.now(ZoneInfo(get_settings().dreaming_timezone))
    lines = [
        "REQUEST CONTEXT：",
        f"- trace_id: {request_context.get('trace_id', '')}",
        f"- channel: {request_context.get('channel', 'web')}",
        f"- locale: {request_context.get('locale', 'zh-TW')}",
        f"- persona_id: {request_context.get('persona_id', 'default')}",
        f"- message_type: {request_context.get('message_type', 'user')}",
        f"- current_time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')} ({now.strftime('%A')})",
    ]
    return "\n".join(lines)

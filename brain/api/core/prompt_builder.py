"""Prompt assembly for the chat generation flow."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from config import get_settings
from core.pipeline import enforce_context_budget
from infra.reflection import (
    compress_text,
    select_recent_messages,
    summarize_message_history,
)
from knowledge.workspace import load_core_workspace_context

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


def build_chat_messages(
    user_message: str,
    request_context: dict[str, Any],
    session_messages: list[dict[str, Any]],
    *,
    allow_tools: bool = True,
) -> list[dict[str, str]]:
    """Build the system and conversation messages for the LLM call.

    Knowledge and memory retrieval are handled by tool calls (search_knowledge,
    search_memory) during the agent loop — they are NOT injected into the prompt.
    """
    cfg = get_settings()
    workspace = load_core_workspace_context(
        str(request_context.get("persona_id", "default")),
        project_id=str(request_context.get("project_id", "default")),
    )
    history_summary = summarize_message_history(session_messages)
    workspace_blocks = [
        _format_workspace_block(label, workspace[label.lower()], getattr(cfg, budget_attr))
        for label, budget_attr in _WORKSPACE_BLOCK_CONFIG
    ]

    tool_instructions = (
        "你可以使用 search_knowledge 和 search_memory 工具來查詢知識庫和記憶，請在需要時主動呼叫。"
        "當使用者要求你記住某事、或對話中出現值得長期保留的偏好/事實/指令時，使用 save_memory 工具儲存。"
        "儲存時用簡潔的陳述句（如「使用者是男生」），不要儲存閒聊或普通問題。"
        if allow_tools
        else ""
    )
    answer_rules = (
        "回答規則：如果資訊不足，先嘗試使用工具搜尋；若仍不足，直接說明缺少什麼；若問題涉及流程，給出清楚下一步；除非使用者要求，否則用繁體中文。"
        if allow_tools
        else "回答規則：直接根據目前對話回答；如果資訊不足，直接說明缺少什麼；若問題涉及流程，給出清楚下一步；除非使用者要求，否則用繁體中文。"
    )

    system_prompt = "\n\n".join(
        block
        for block in [
            "你是 `openVman Brain` 的對話核心。回答時要遵守以下上下文，且不要編造不存在的資訊。",
            tool_instructions,
            *workspace_blocks,
            _format_request_context(request_context),
            history_summary,
            answer_rules,
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

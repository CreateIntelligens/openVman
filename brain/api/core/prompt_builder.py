"""Prompt assembly for the chat generation flow."""

from __future__ import annotations

from typing import Any

from config import get_settings
from core.pipeline import enforce_context_budget
from infra.reflection import (
    compress_text,
    select_recent_messages,
    summarize_message_history,
)
from knowledge.workspace import load_core_workspace_context


def build_chat_messages(
    user_message: str,
    request_context: dict[str, Any],
    session_messages: list[dict[str, Any]],
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
    system_prompt = "\n\n".join(
        block
        for block in [
            "你是 `openVman Brain` 的對話核心。回答時要遵守以下上下文，且不要編造不存在的資訊。"
            "你可以使用 search_knowledge 和 search_memory 工具來查詢知識庫和記憶，請在需要時主動呼叫。",
            _format_workspace_block("SOUL", workspace["soul"], cfg.prompt_soul_char_budget),
            _format_workspace_block("MEMORY", workspace["memory"], cfg.prompt_memory_char_budget),
            _format_workspace_block("AGENTS", workspace["agents"], cfg.prompt_agents_char_budget),
            _format_workspace_block("TOOLS", workspace["tools"], cfg.prompt_tools_char_budget),
            _format_workspace_block("LEARNINGS", workspace["learnings"], cfg.prompt_learnings_char_budget),
            _format_workspace_block("ERRORS", workspace["errors"], cfg.prompt_errors_char_budget),
            _format_request_context(request_context),
            history_summary,
            "回答規則：如果資訊不足，先嘗試使用工具搜尋；若仍不足，直接說明缺少什麼；若問題涉及流程，給出清楚下一步；除非使用者要求，否則用繁體中文。",
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
    lines = [
        "REQUEST CONTEXT：",
        f"- trace_id: {request_context.get('trace_id', '')}",
        f"- channel: {request_context.get('channel', 'web')}",
        f"- locale: {request_context.get('locale', 'zh-TW')}",
        f"- persona_id: {request_context.get('persona_id', 'default')}",
        f"- message_type: {request_context.get('message_type', 'user')}",
    ]
    return "\n".join(lines)

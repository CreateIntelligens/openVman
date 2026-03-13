"""Helpers for curating recent session context before generation."""

from __future__ import annotations

from typing import Any

from config import get_settings


def select_recent_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Keep only the most recent messages that fit the configured round limit."""
    cfg = get_settings()
    max_messages = max(cfg.short_term_memory_rounds * 2, 8)
    trimmed = messages[-max_messages:]
    selected: list[dict[str, str]] = []
    used_chars = 0

    for message in reversed(trimmed):
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        budget = len(content) + 16
        if selected and used_chars + budget > cfg.prompt_history_char_budget:
            break
        selected.append(
            {
                "role": str(message.get("role", "user")),
                "content": compress_text(content, 600),
            }
        )
        used_chars += budget

    selected.reverse()
    return selected


def summarize_supporting_context(
    results: list[dict[str, Any]],
    label: str,
    max_chars: int | None = None,
    max_items: int = 4,
) -> str:
    """Format retrieval results into a readable prompt block."""
    cfg = get_settings()
    budget = max_chars or cfg.prompt_context_char_budget
    if not results:
        return f"{label}：無"

    lines = [f"{label}："]
    used_chars = len(lines[0])
    for index, result in enumerate(results[:max_items], start=1):
        text = compress_text(str(result.get("text", "")).strip(), 260)
        source = str(result.get("source", "workspace")).strip()
        line = f"{index}. [{source}] {text}"
        if used_chars + len(line) > budget and len(lines) > 1:
            lines.append("... 其餘內容已省略")
            break
        lines.append(line)
        used_chars += len(line)
    return "\n".join(lines)


def summarize_message_history(messages: list[dict[str, Any]]) -> str:
    """Compress older session messages into a short textual recap."""
    cfg = get_settings()
    if not messages:
        return ""

    older_messages = messages[:-max(cfg.short_term_memory_rounds * 2, 8)]
    if not older_messages:
        return ""

    lines = ["較早對話摘要："]
    used_chars = len(lines[0])
    for message in older_messages[-8:]:
        role = str(message.get("role", "user"))
        content = compress_text(str(message.get("content", "")).strip(), 120)
        if not content:
            continue
        line = f"- {role}: {content}"
        if used_chars + len(line) > cfg.prompt_history_summary_char_budget:
            lines.append("- 其餘較早內容已省略")
            break
        lines.append(line)
        used_chars += len(line)

    return "\n".join(lines) if len(lines) > 1 else ""


def compress_text(text: str, max_chars: int) -> str:
    """Trim text aggressively while preserving both the head and tail."""
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    if max_chars <= 24:
        return normalized[:max_chars]

    head = max_chars // 2
    tail = max_chars - head - 7
    return f"{normalized[:head]} ... {normalized[-tail:]}"

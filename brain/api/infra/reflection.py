"""Helpers for curating recent session context before generation."""

from __future__ import annotations

from typing import Any

from config import get_settings
from memory.auto_recall import strip_recall_noise


def select_recent_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Keep only the most recent messages that fit the configured round limit."""
    cfg = get_settings()
    max_messages = max(cfg.short_term_memory_rounds * 2, 8)
    trimmed = messages[-max_messages:]
    selected: list[dict[str, str]] = []
    used_chars = 0

    for message in reversed(trimmed):
        content = strip_recall_noise(str(message.get("content", "")).strip())
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
        content = compress_text(strip_recall_noise(str(message.get("content", "")).strip()), 120)
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


def compress_text_keeping(text: str, max_chars: int, start: str, end: str) -> str:
    """Like ``compress_text``, but the span from ``start`` to ``end`` is never cut.

    保護規則夾在 system prompt 中段；整段壓縮保留頭尾會把它切掉，所以先把它拿出來，
    其餘內容依原本比例分配剩下的字數。只剩它放得下時就只留它。
    """
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    begin = normalized.find(start)
    finish = normalized.find(end, begin) if begin >= 0 else -1
    if begin < 0 or finish < 0:
        return compress_text(normalized, max_chars)
    finish += len(end)
    kept = normalized[begin:finish]
    before, after = normalized[:begin].strip(), normalized[finish:].strip()
    room = max_chars - len(kept) - 2
    if room <= 0 or not (before or after):
        return kept
    before_room = room * len(before) // (len(before) + len(after))
    parts = (
        compress_text(before, before_room) if before_room > 0 else "",
        kept,
        compress_text(after, room - before_room) if room - before_room > 0 else "",
    )
    return " ".join(part for part in parts if part)

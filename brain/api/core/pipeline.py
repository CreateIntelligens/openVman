"""Route and context budget enforcement for the brain message pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from infra.reflection import compress_text
from protocol.message_envelope import BrainMessage


@dataclass(slots=True, frozen=True)
class RouteDecision:
    """Immutable routing result for a brain message."""

    path: str       # "direct" | "rag" | "tool"
    skip_rag: bool
    skip_tools: bool


_DIRECT_ROLES = frozenset({"system", "assistant", "control"})


def route_message(brain_message: BrainMessage) -> RouteDecision:
    """Decide the processing path based on message role."""
    if brain_message.role in _DIRECT_ROLES:
        return RouteDecision(path="direct", skip_rag=True, skip_tools=True)
    if brain_message.role == "tool":
        return RouteDecision(path="tool", skip_rag=True, skip_tools=False)
    return RouteDecision(path="rag", skip_rag=False, skip_tools=False)


def enforce_context_budget(
    messages: list[dict[str, Any]],
    *,
    total_char_budget: int,
) -> list[dict[str, Any]]:
    """Trim messages to fit within budget.

    Strategy order:
    1. Drop oldest history turns (keep system + last user)
    2. Compress system prompt (head+tail truncation)
    """
    if _total_chars(messages) <= total_char_budget:
        return list(messages)

    trimmed = _trim_history(messages, total_char_budget)
    if _total_chars(trimmed) <= total_char_budget:
        return trimmed

    return _compress_system(trimmed, total_char_budget)


def _total_chars(messages: list[dict[str, Any]]) -> int:
    return sum(len(str(m.get("content", ""))) for m in messages)


def _trim_history(
    messages: list[dict[str, Any]],
    budget: int,
) -> list[dict[str, Any]]:
    """Drop oldest conversation turns between system and the last user message."""
    if len(messages) <= 2:
        return list(messages)

    system = messages[0] if messages[0].get("role") == "system" else None
    last_user = messages[-1]
    history = messages[1:-1] if system else messages[:-1]

    kept: list[dict[str, Any]] = []
    base_cost = len(str(last_user.get("content", "")))
    if system:
        base_cost += len(str(system.get("content", "")))

    remaining = budget - base_cost
    for msg in reversed(history):
        cost = len(str(msg.get("content", "")))
        if remaining - cost < 0:
            break
        kept.append(msg)
        remaining -= cost

    kept.reverse()
    result: list[dict[str, Any]] = []
    if system:
        result.append(system)
    result.extend(kept)
    result.append(last_user)
    return result


def _compress_system(
    messages: list[dict[str, Any]],
    budget: int,
) -> list[dict[str, Any]]:
    """Compress the system prompt to fit remaining budget."""
    if not messages or messages[0].get("role") != "system":
        return list(messages)

    non_system_cost = sum(
        len(str(m.get("content", "")))
        for m in messages[1:]
    )
    system_budget = max(budget - non_system_cost, 0)
    compressed_content = compress_text(
        str(messages[0].get("content", "")),
        system_budget,
    )

    return [
        {**messages[0], "content": compressed_content},
        *messages[1:],
    ]

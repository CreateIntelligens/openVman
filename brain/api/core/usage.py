"""Per-request usage attribution scope and the normalized LLM usage shape.

The scope is a ``ContextVar`` so that any LLM call made while serving a
request (agent loop, recall summaries, tool phases) is attributed to the
same user / project / session / trace without threading arguments through
every call site. ``asyncio.to_thread`` copies the context, so threads see it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_tokens",
    "reasoning_tokens",
)


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """Token counts for one model call, normalized across providers."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0

    def is_empty(self) -> bool:
        return not (self.input_tokens or self.output_tokens or self.total_tokens)

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }


def _read_int(obj: Any, name: str) -> int:
    if obj is None:
        return 0
    value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _read_attr(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def usage_from_response(usage_obj: Any) -> LLMUsage | None:
    """Normalize an OpenAI-compatible ``usage`` object (or dict) into LLMUsage.

    Gemini / OpenAI / vLLM all follow the ``prompt_tokens`` /
    ``completion_tokens`` naming; cached and reasoning counts live in the
    optional ``*_tokens_details`` sub-objects.
    """
    if usage_obj is None:
        return None
    input_tokens = _read_int(usage_obj, "prompt_tokens")
    output_tokens = _read_int(usage_obj, "completion_tokens")
    total_tokens = _read_int(usage_obj, "total_tokens") or (input_tokens + output_tokens)
    usage = LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_tokens=_read_int(
            _read_attr(usage_obj, "prompt_tokens_details"),
            "cached_tokens",
        ),
        reasoning_tokens=_read_int(
            _read_attr(usage_obj, "completion_tokens_details"),
            "reasoning_tokens",
        ),
    )
    return None if usage.is_empty() else usage


@dataclass(slots=True)
class UsageScope:
    """Attribution for every usage event recorded while the scope is active."""

    kind: str = "chat"
    user_id: str = ""
    role: str = ""
    project_id: str = "default"
    session_id: str = ""
    persona_id: str = "default"
    trace_id: str = ""
    channel: str = ""
    collected: list[dict[str, Any]] = field(default_factory=list)


_usage_scope: ContextVar[UsageScope | None] = ContextVar("brain_usage_scope", default=None)


def current_usage_scope() -> UsageScope | None:
    return _usage_scope.get()


@contextmanager
def usage_scope(**fields: Any) -> Iterator[UsageScope]:
    scope = UsageScope(**fields)
    token = _usage_scope.set(scope)
    try:
        yield scope
    finally:
        _usage_scope.reset(token)


def summarize_collected(scope: UsageScope) -> dict[str, Any]:
    """Aggregate the events collected in one scope for the API response."""
    totals = LLMUsage().as_dict()
    by_model: dict[str, dict[str, int]] = {}
    for event in scope.collected:
        usage = {
            name: int(event.get(name, 0) or 0)
            for name in _TOKEN_FIELDS
        }
        key = f"{event.get('provider', '')}/{event.get('model', '')}"
        bucket = by_model.setdefault(key, {"calls": 0, **LLMUsage().as_dict()})
        bucket["calls"] += 1
        for name, value in usage.items():
            totals[name] += value
            bucket[name] += value
    return {"calls": len(scope.collected), **totals, "by_model": by_model}

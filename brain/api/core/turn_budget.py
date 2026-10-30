"""Deadlines for one chat turn, so no node on the answer path waits unbounded.

``/brain/chat`` binds a :class:`TurnBudget` for the request. Everything the turn
runs (agent loop rounds, tool calls, LLM hops) reads it from a context var, the
same way it reads the cancel event: ``asyncio.to_thread`` copies context vars and
the tool executor re-enters the parent context.

Code that runs without a bound budget (ingestion, graph extraction, background
summaries) keeps the longer per-call timeouts; that is how the answer path and
batch work get different limits from the same clients.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import monotonic
from typing import Any


@dataclass(slots=True)
class TurnBudget:
    """Wall-clock budget of one chat turn (monotonic seconds)."""

    seconds: float
    started: float = field(default_factory=monotonic)

    @property
    def deadline(self) -> float:
        return self.started + self.seconds

    def remaining(self) -> float:
        return self.deadline - monotonic()

    def expired(self) -> bool:
        return self.remaining() <= 0

    def elapsed_ms(self) -> float:
        return (monotonic() - self.started) * 1000.0


_turn_budget: contextvars.ContextVar[TurnBudget | None] = contextvars.ContextVar(
    "chat_turn_budget", default=None,
)


@contextmanager
def bind_turn_budget(seconds: float, *, started: float | None = None) -> Iterator[TurnBudget]:
    budget = TurnBudget(seconds=seconds, started=started if started is not None else monotonic())
    token = _turn_budget.set(budget)
    try:
        yield budget
    finally:
        _turn_budget.reset(token)


def current_turn_budget() -> TurnBudget | None:
    return _turn_budget.get()


def number_setting(cfg: Any, name: str, default: float) -> float:
    """Read a numeric setting, falling back to *default* for missing or mock values.

    測試常用 MagicMock 當設定，沒設定的欄位會拿到 MagicMock；逾時值拿到它會在比較時
    爆掉，所以只接受真的數字。
    """
    value = getattr(cfg, name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(default)
    return float(value)


def current_trace_id() -> str:
    """The chat turn's trace id (bound on the usage scope by /brain/chat), or ""."""
    from core.usage import current_usage_scope

    scope = current_usage_scope()
    return str(getattr(scope, "trace_id", "") or "") if scope is not None else ""


def error_fields(exc: BaseException | None) -> dict[str, str]:
    """``error_type`` plus a message; httpx timeouts often have an empty ``str(exc)``."""
    if exc is None:
        return {}
    message = str(exc).strip()
    return {"error_type": type(exc).__name__, "error": (message or type(exc).__name__)[:300]}

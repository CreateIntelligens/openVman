"""Compatibility facade for the shared typed decision-provider chain.

Existing Brain call sites keep their established `jev_*` function names while
the active provider can be Clef, Jev, or OpenAI Decisions.
"""

from __future__ import annotations

from typing import Any


def jev_available() -> bool:
    """Return whether any enabled decision provider is reachable/configured."""
    from core.decision_router import decision_available

    return decision_available()


def jev_nouls(
    state: str | dict[str, Any] | list[Any] | None,
    questions: dict[str, dict[str, Any]],
    *,
    timeout: float,
    purpose: str,
) -> dict[str, float]:
    from core.decision_router import decide_nouls

    return decide_nouls(state, questions, timeout=timeout, purpose=purpose)


def jev_noul(
    state: str | dict[str, Any] | list[Any] | None,
    question: dict[str, Any],
    *,
    timeout: float,
    purpose: str,
) -> float:
    from core.decision_router import decide_noul

    return decide_noul(state, question, timeout=timeout, purpose=purpose)


__all__ = ["jev_available", "jev_noul", "jev_nouls"]

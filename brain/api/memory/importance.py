"""Heuristic importance scoring for memory records."""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Signal patterns — ordered by priority (first match wins per category)
# ---------------------------------------------------------------------------

_HIGH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:請|要)?記住", re.IGNORECASE),
    re.compile(r"(?:我|用戶)(?:偏好|喜歡|討厭|不喜歡|不要|總是|從不)", re.IGNORECASE),
    re.compile(r"(?:prefer|always|never|remember|don'?t)\b", re.IGNORECASE),
    re.compile(r"(?:指令|指示|規則|要求|糾正|修正|更正)", re.IGNORECASE),
    re.compile(r"(?:instruction|correction|rule|must|should not)\b", re.IGNORECASE),
]

_MEDIUM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b"),  # dates
    re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b"),  # proper names (multi-word)
    re.compile(r"\b\d{3,}\b"),  # significant numbers
    re.compile(
        r"(?:email|phone|電話|信箱|地址|address|聯絡|contact)\b", re.IGNORECASE,
    ),
    re.compile(r"(?:生日|birthday|anniversary|紀念日)\b", re.IGNORECASE),
]

_LOW_SCORE = 0.1
_MEDIUM_RANGE = (0.3, 0.6)
_HIGH_RANGE = (0.7, 1.0)


@dataclass(frozen=True, slots=True)
class ImportanceResult:
    """Immutable result of importance scoring."""

    score: float  # 0.0 – 1.0
    level: str  # "high" | "medium" | "low"
    signals: tuple[str, ...]  # matched pattern descriptions


def score_importance(text: str) -> ImportanceResult:
    """Score the importance of a piece of text using regex heuristics.

    Returns an ImportanceResult with score, level, and matched signals.
    """
    if not text or not text.strip():
        return ImportanceResult(score=_LOW_SCORE, level="low", signals=())

    # Check tiers in priority order (first match wins)
    _TIERS: tuple[tuple[str, list[re.Pattern[str]], tuple[float, float]], ...] = (
        ("high", _HIGH_PATTERNS, _HIGH_RANGE),
        ("medium", _MEDIUM_PATTERNS, _MEDIUM_RANGE),
    )

    for level, patterns, score_range in _TIERS:
        signals = _match_patterns(text, level, patterns)
        if signals:
            ratio = min(len(signals) / len(patterns), 1.0)
            score = score_range[0] + ratio * (score_range[1] - score_range[0])
            return ImportanceResult(
                score=round(score, 2),
                level=level,
                signals=tuple(signals),
            )

    return ImportanceResult(score=_LOW_SCORE, level="low", signals=())


def _match_patterns(
    text: str,
    level: str,
    patterns: list[re.Pattern[str]],
) -> list[str]:
    """Return signal labels for all patterns that match *text*."""
    return [
        f"{level}:{pattern.pattern[:30]}"
        for pattern in patterns
        if pattern.search(text)
    ]

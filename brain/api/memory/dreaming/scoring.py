"""Weighted scoring engine for dreaming memory consolidation.

Pure functions — no side effects, no I/O. Easy to test independently.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Signal weights (must sum to 1.0)
# ---------------------------------------------------------------------------

SIGNAL_WEIGHTS: dict[str, float] = {
    "frequency": 0.24,
    "relevance": 0.30,
    "query_diversity": 0.15,
    "recency": 0.15,
    "consolidation": 0.10,
    "importance": 0.06,
}

_RECENCY_HALF_LIFE_DAYS = 7.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_candidate(candidate: dict[str, Any]) -> float:
    """Compute the weighted consolidation score for a candidate."""
    signals = candidate.get("signals", {})
    total = sum(
        weight * _clamp(float(signals.get(name, 0.0)))
        for name, weight in SIGNAL_WEIGHTS.items()
    )
    return round(total, 4)


def passes_threshold(
    candidate: dict[str, Any],
    *,
    min_score: float = 0.80,
    min_recall_count: int = 3,
    min_unique_queries: int = 3,
) -> bool:
    """Check whether a candidate meets the promotion thresholds."""
    signals = candidate.get("signals", {})
    return (
        candidate.get("score", 0.0) >= min_score and
        int(signals.get("raw_recall_count", 0)) >= min_recall_count and
        int(signals.get("raw_unique_queries", 0)) >= min_unique_queries
    )


# ---------------------------------------------------------------------------
# Signal normalisers
# ---------------------------------------------------------------------------

def normalise_frequency(recall_count: int, max_expected: int = 20) -> float:
    """Normalise hit count to 0–1 using log scaling."""
    if recall_count <= 0:
        return 0.0
    return _clamp(math.log1p(recall_count) / math.log1p(max_expected))


def normalise_relevance(scores: list[float]) -> float:
    """Average retrieval score, assumed already in 0–1 range."""
    return _clamp(sum(scores) / len(scores)) if scores else 0.0


def normalise_query_diversity(unique_queries: int, days: int) -> float:
    """Ratio of unique queries per day, capped at 1."""
    return _clamp(unique_queries / days) if days > 0 else 0.0


def normalise_recency(
    last_seen_iso: str,
    now: datetime | None = None,
    half_life_days: float = _RECENCY_HALF_LIFE_DAYS,
) -> float:
    """Exponential time decay — half-life defaults to 7 days."""
    last_seen = _parse_date(last_seen_iso)
    if not last_seen:
        return 0.0

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    age_days = max((now - last_seen).total_seconds() / 86400, 0.0)
    return _clamp(math.exp(-0.693 * age_days / half_life_days))


def normalise_consolidation(cross_day_count: int, max_expected: int = 7) -> float:
    """Cross-day repeat appearances, normalised to 0–1."""
    return _clamp(cross_day_count / max_expected) if cross_day_count > 0 else 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_signals(
    *,
    recall_count: int = 0,
    relevance_scores: list[float] | None = None,
    unique_queries: int = 0,
    lookback_days: int = 7,
    last_seen_iso: str = "",
    cross_day_count: int = 0,
    importance_score: float = 0.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a normalised signals dict from raw metrics."""
    return {
        "frequency": normalise_frequency(recall_count),
        "relevance": normalise_relevance(relevance_scores or []),
        "query_diversity": normalise_query_diversity(unique_queries, lookback_days),
        "recency": normalise_recency(last_seen_iso, now=now),
        "consolidation": normalise_consolidation(cross_day_count),
        "importance": _clamp(importance_score),
        "raw_recall_count": recall_count,
        "raw_unique_queries": unique_queries,
    }


def _parse_date(iso_str: str) -> datetime | None:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))

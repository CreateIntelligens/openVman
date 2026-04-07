"""Tests for the dreaming scoring engine."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from memory.dreaming.scoring import (
    build_signals,
    normalise_consolidation,
    normalise_frequency,
    normalise_query_diversity,
    normalise_recency,
    normalise_relevance,
    passes_threshold,
    score_candidate,
)


class TestNormalisers:
    def test_frequency_zero(self):
        assert normalise_frequency(0) == 0.0

    def test_frequency_positive(self):
        score = normalise_frequency(10)
        assert 0.0 < score <= 1.0

    def test_frequency_capped(self):
        assert normalise_frequency(1000) == 1.0

    def test_relevance_empty(self):
        assert normalise_relevance([]) == 0.0

    def test_relevance_average(self):
        assert normalise_relevance([0.8, 0.6]) == pytest.approx(0.7)

    def test_query_diversity_zero(self):
        assert normalise_query_diversity(0, 7) == 0.0

    def test_query_diversity_positive(self):
        result = normalise_query_diversity(3, 7)
        assert 0.0 < result <= 1.0

    def test_recency_recent(self):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(hours=1)).isoformat()
        score = normalise_recency(recent, now=now)
        assert score > 0.9

    def test_recency_old(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=30)).isoformat()
        score = normalise_recency(old, now=now)
        assert score < 0.1

    def test_recency_empty(self):
        assert normalise_recency("") == 0.0

    def test_consolidation_zero(self):
        assert normalise_consolidation(0) == 0.0

    def test_consolidation_positive(self):
        assert normalise_consolidation(3, max_expected=7) == pytest.approx(3 / 7)


class TestScoreCandidate:
    def test_all_zero_signals(self):
        candidate = {"signals": {}}
        assert score_candidate(candidate) == 0.0

    def test_all_max_signals(self):
        candidate = {
            "signals": {
                "frequency": 1.0,
                "relevance": 1.0,
                "query_diversity": 1.0,
                "recency": 1.0,
                "consolidation": 1.0,
                "importance": 1.0,
            }
        }
        assert score_candidate(candidate) == pytest.approx(1.0)

    def test_partial_signals(self):
        candidate = {
            "signals": {
                "frequency": 0.5,
                "relevance": 0.8,
            }
        }
        expected = 0.24 * 0.5 + 0.30 * 0.8
        assert score_candidate(candidate) == pytest.approx(expected, abs=0.001)


class TestPassesThreshold:
    def test_passes_all(self):
        c = {
            "score": 0.5,
            "signals": {"raw_recall_count": 3, "raw_unique_queries": 2},
        }
        assert passes_threshold(c, min_score=0.45, min_recall_count=2, min_unique_queries=1)

    def test_fails_score(self):
        c = {
            "score": 0.3,
            "signals": {"raw_recall_count": 3, "raw_unique_queries": 2},
        }
        assert not passes_threshold(c, min_score=0.45)

    def test_fails_recall_count(self):
        c = {
            "score": 0.5,
            "signals": {"raw_recall_count": 1, "raw_unique_queries": 2},
        }
        assert not passes_threshold(c, min_recall_count=2)


class TestBuildSignals:
    def test_builds_all_keys(self):
        signals = build_signals(
            recall_count=5,
            relevance_scores=[0.8, 0.9],
            unique_queries=3,
            lookback_days=7,
            last_seen_iso=datetime.now(timezone.utc).isoformat(),
            cross_day_count=2,
            importance_score=0.7,
        )
        assert "frequency" in signals
        assert "relevance" in signals
        assert "query_diversity" in signals
        assert "recency" in signals
        assert "consolidation" in signals
        assert "importance" in signals
        assert signals["raw_recall_count"] == 5
        assert signals["raw_unique_queries"] == 3

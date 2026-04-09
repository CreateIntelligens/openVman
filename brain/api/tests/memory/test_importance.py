"""Tests for memory importance scoring heuristics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from memory.importance import ImportanceResult, score_importance


class TestScoreImportance:
    def test_empty_text_returns_low(self):
        """Empty or whitespace-only text should score low."""
        assert score_importance("").level == "low"
        assert score_importance("   ").level == "low"
        assert score_importance("").score == pytest.approx(0.1)

    def test_preference_signal_is_high(self):
        """Text containing preference keywords should score high."""
        result = score_importance("我偏好簡短回覆")
        assert result.level == "high"
        assert result.score >= 0.7

    def test_instruction_signal_is_high(self):
        """Text containing instruction/correction keywords should score high."""
        result = score_importance("請記住我的名字是小明")
        assert result.level == "high"
        assert result.score >= 0.7
        assert len(result.signals) >= 1

    def test_date_signal_is_medium(self):
        """Text containing dates should score medium."""
        result = score_importance("會議時間是 2026-03-15 下午三點")
        assert result.level == "medium"
        assert 0.3 <= result.score <= 0.6

    def test_contact_info_is_medium(self):
        """Text containing contact-related keywords should score medium."""
        result = score_importance("他的 email 是 test@example.com")
        assert result.level == "medium"
        assert 0.3 <= result.score <= 0.6

    def test_plain_text_is_low(self):
        """Text with no special signals should score low."""
        result = score_importance("今天天氣真好")
        assert result.level == "low"
        assert result.score == pytest.approx(0.1)

    def test_result_is_frozen(self):
        """ImportanceResult should be immutable."""
        result = score_importance("test")
        with pytest.raises(AttributeError):
            result.score = 0.5  # type: ignore[misc]

    def test_multiple_high_signals_increase_score(self):
        """Multiple high signals should yield a higher score within the high range."""
        single = score_importance("記住這個")
        multi = score_importance("請記住，我偏好這個指令的規則")
        assert multi.score >= single.score

    def test_high_takes_priority_over_medium(self):
        """When both high and medium signals are present, high wins."""
        result = score_importance("記住會議日期 2026-03-15")
        assert result.level == "high"

    def test_english_preference_signal(self):
        """English preference keywords should also score high."""
        result = score_importance("I always prefer dark mode")
        assert result.level == "high"
        assert result.score >= 0.7

"""Retention limits on conversation history: query 6 months, export 3.

兩個數字不同是刻意的——看是為了查問題，下載是把資料帶離系統。規則與 JTAI
後台一致（tests/hciot/test_history_date_limits.py）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from routes.sessions import (
    _EXPORT_MAX_MONTHS,
    _HISTORY_MAX_MONTHS,
    _months_ago,
    _validate_date_range,
)

_TZ_TAIPEI = timezone(timedelta(hours=8))


def test_months_ago_counts_calendar_months_not_fixed_days():
    base = datetime(2026, 8, 18, tzinfo=_TZ_TAIPEI)

    assert _months_ago(3, base) == date(2026, 5, 18)
    assert _months_ago(6, base) == date(2026, 2, 18)


def test_months_ago_clamps_to_the_shorter_month():
    # 3/31 往回一個月沒有 2/31。直接減 30 天會得到 3/1，界線會隨月份長度漂移。
    assert _months_ago(1, datetime(2026, 3, 31, tzinfo=_TZ_TAIPEI)) == date(2026, 2, 28)
    assert _months_ago(1, datetime(2024, 3, 31, tzinfo=_TZ_TAIPEI)) == date(2024, 2, 29)


def test_months_ago_crosses_the_year_boundary():
    assert _months_ago(3, datetime(2026, 2, 10, tzinfo=_TZ_TAIPEI)) == date(2025, 11, 10)


def test_query_rejects_a_start_date_beyond_six_months():
    with pytest.raises(HTTPException) as caught:
        _validate_date_range(
            "2020-01-01", None,
            max_months=_HISTORY_MAX_MONTHS,
            limit_msg="查詢區間限制為半年內",
        )

    assert caught.value.status_code == 400
    assert "半年" in caught.value.detail


def test_query_accepts_a_date_inside_the_window():
    inside = _months_ago(_HISTORY_MAX_MONTHS - 1).isoformat()

    _validate_date_range(
        inside, None,
        max_months=_HISTORY_MAX_MONTHS,
        limit_msg="查詢區間限制為半年內",
    )


def test_export_window_is_tighter_than_the_query_window():
    # 四個月前查得到，但載不回來。
    four_months_ago = _months_ago(4).isoformat()

    _validate_date_range(
        four_months_ago, None,
        max_months=_HISTORY_MAX_MONTHS,
        limit_msg="查詢區間限制為半年內",
    )
    with pytest.raises(HTTPException) as caught:
        _validate_date_range(
            four_months_ago, None,
            max_months=_EXPORT_MAX_MONTHS,
            limit_msg="下載區間限制為近三個月內",
        )

    assert "三個月" in caught.value.detail


def test_end_date_before_start_date_is_rejected():
    with pytest.raises(HTTPException) as caught:
        _validate_date_range(
            "2026-08-01", "2026-07-01",
            max_months=_HISTORY_MAX_MONTHS,
            limit_msg="查詢區間限制為半年內",
        )

    assert "結束日期不能早於開始日期" in caught.value.detail


@pytest.mark.parametrize("bad", ["2026-13-01", "not-a-date", "2026/01/01"])
def test_malformed_dates_are_rejected_before_hitting_the_store(bad):
    with pytest.raises(HTTPException) as caught:
        _validate_date_range(
            bad, None,
            max_months=_HISTORY_MAX_MONTHS,
            limit_msg="查詢區間限制為半年內",
        )

    assert caught.value.status_code == 400
    assert "YYYY-MM-DD" in caught.value.detail

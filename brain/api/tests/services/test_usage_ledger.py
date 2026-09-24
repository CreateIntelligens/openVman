"""Tests for the usage ledger and usage scope aggregation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from core.usage import (
    LLMUsage,
    current_usage_scope,
    summarize_collected,
    usage_from_response,
    usage_scope,
)
from infra import usage_ledger


@pytest.fixture()
def ledger(tmp_path: Path):
    usage_ledger.set_usage_db_path(tmp_path / "usage.db")
    yield usage_ledger
    usage_ledger.set_usage_db_path(None)


def test_usage_from_response_reads_openai_shape():
    class Details:
        cached_tokens = 7

    class Usage:
        prompt_tokens = 100
        completion_tokens = 20
        total_tokens = 120
        prompt_tokens_details = Details()
        completion_tokens_details = None

    usage = usage_from_response(Usage())
    assert usage == LLMUsage(100, 20, 120, 7, 0)


def test_usage_from_response_accepts_dict_and_fills_total():
    usage = usage_from_response({"prompt_tokens": 3, "completion_tokens": 4})
    assert usage is not None
    assert usage.total_tokens == 7


def test_usage_from_response_empty_is_none():
    assert usage_from_response(None) is None
    assert usage_from_response({"prompt_tokens": 0, "completion_tokens": 0}) is None


def test_record_event_uses_scope_and_collects(ledger):
    with usage_scope(
        kind="chat", user_id="u1", project_id="p1", session_id="s1", trace_id="t1",
    ) as scope:
        assert current_usage_scope() is scope
        ledger.record_usage_event(
            provider="gemini", model="flash", usage=LLMUsage(10, 5, 15), latency_ms=12.5,
        )
        ledger.record_usage_event(
            provider="gemini", model="flash", usage=LLMUsage(20, 5, 25), latency_ms=8.0,
        )
    assert current_usage_scope() is None

    summary = summarize_collected(scope)
    assert summary["calls"] == 2
    assert summary["input_tokens"] == 30
    assert summary["total_tokens"] == 40
    assert summary["by_model"]["gemini/flash"]["calls"] == 2
    assert summary["latency_ms"] == 20.5
    assert summary["by_model"]["gemini/flash"]["latency_ms"] == 20.5

    events = ledger.list_usage_events(trace_id="t1")
    assert len(events) == 2
    assert events[0]["user_id"] == "u1"
    assert events[0]["project_id"] == "p1"
    assert events[0]["session_id"] == "s1"
    assert events[0]["kind"] == "chat"


def test_record_without_scope_is_background(ledger):
    ledger.record_usage_event(provider="openai", model="gpt", usage=None)
    events = ledger.list_usage_events()
    assert events[0]["kind"] == "background"
    assert events[0]["total_tokens"] == 0
    assert events[0]["user_id"] == ""


def test_summary_groups_and_filters(ledger):
    with usage_scope(user_id="a", project_id="p"):
        ledger.record_usage_event(provider="g", model="m1", usage=LLMUsage(1, 1, 2))
        ledger.record_usage_event(provider="g", model="m2", usage=LLMUsage(5, 5, 10))
    with usage_scope(user_id="b", project_id="p"):
        ledger.record_usage_event(provider="g", model="m1", usage=LLMUsage(3, 3, 6))

    by_model = ledger.summarize_usage(group_by="model", project_id="p")
    assert by_model["totals"]["total_tokens"] == 18
    assert {g["model"]: g["total_tokens"] for g in by_model["groups"]} == {"m1": 8, "m2": 10}

    by_user = ledger.summarize_usage(group_by="user")
    assert {g["user_id"]: g["calls"] for g in by_user["groups"]} == {"a": 2, "b": 1}

    only_b = ledger.summarize_usage(group_by="model", user_id="b")
    assert only_b["totals"]["total_tokens"] == 6

    with pytest.raises(ValueError):
        ledger.summarize_usage(group_by="nope")


def _record_at(ledger, monkeypatch, when: str, **kwargs):
    """Write one event stamped at *when* so bucket boundaries are testable."""
    monkeypatch.setattr(ledger, "_now_iso", lambda: when)
    ledger.record_usage_event(**kwargs)


def test_timeseries_buckets_by_day_and_splits_by_group(ledger, monkeypatch):
    with usage_scope(user_id="a", project_id="p1"):
        _record_at(
            ledger, monkeypatch, "2026-09-03T01:00:00+00:00",
            provider="g", model="m", usage=LLMUsage(1, 1, 2),
        )
        _record_at(
            ledger, monkeypatch, "2026-09-03T23:00:00+00:00",
            provider="g", model="m", usage=LLMUsage(2, 2, 4),
        )
    with usage_scope(user_id="b", project_id="p2"):
        _record_at(
            ledger, monkeypatch, "2026-09-04T05:00:00+00:00",
            provider="g", model="m", usage=LLMUsage(5, 5, 10),
        )

    plain = ledger.timeseries_usage(bucket="day")
    assert plain["report_timezone"] == "UTC"
    assert plain["periods"] == ["2026-09-03", "2026-09-04"]
    # 同一天的兩筆要併進同一個 bucket。
    assert [p["total_tokens"] for p in plain["points"]] == [6, 10]

    split = ledger.timeseries_usage(bucket="day", group_by="project")
    assert split["report_timezone"] == "UTC"
    assert {s["project_id"] for s in split["series"]} == {"p1", "p2"}
    p1 = next(s for s in split["series"] if s["project_id"] == "p1")
    assert [p["total_tokens"] for p in p1["points"]] == [6]


def test_timeseries_hour_bucket_separates_same_day_events(ledger, monkeypatch):
    with usage_scope(user_id="a", project_id="p"):
        _record_at(
            ledger, monkeypatch, "2026-09-03T01:00:00+00:00",
            provider="g", model="m", usage=LLMUsage(1, 1, 2),
        )
        _record_at(
            ledger, monkeypatch, "2026-09-03T02:00:00+00:00",
            provider="g", model="m", usage=LLMUsage(2, 2, 4),
        )

    hourly = ledger.timeseries_usage(bucket="hour")
    assert hourly["periods"] == ["2026-09-03T01", "2026-09-03T02"]


def test_timeseries_folds_low_volume_groups_into_other(ledger, monkeypatch):
    """分組是使用者資料，可能有上百個；只留前 N 名，其餘併成 __other__。"""
    for index in range(5):
        with usage_scope(user_id=f"u{index}", project_id=f"p{index}"):
            _record_at(
                ledger, monkeypatch, "2026-09-03T01:00:00+00:00",
                provider="g", model="m",
                usage=LLMUsage(0, 0, 100 - index),
            )

    top2 = ledger.timeseries_usage(bucket="day", group_by="project", limit=2)
    labels = [s["project_id"] for s in top2["series"]]
    assert labels[:2] == ["p0", "p1"]
    assert "__other__" in labels
    other = next(s for s in top2["series"] if s["project_id"] == "__other__")
    # 98 + 97 + 96：其餘三組的總和要完整保留，不能被丟掉。
    assert other["points"][0]["total_tokens"] == 291


def test_timeseries_rejects_unknown_bucket_and_group(ledger):
    with pytest.raises(ValueError):
        ledger.timeseries_usage(bucket="fortnight")
    with pytest.raises(ValueError):
        ledger.timeseries_usage(bucket="day", group_by="nope")


@pytest.mark.parametrize("group_by", ["", "project"])
@pytest.mark.parametrize(
    ("bucket", "before", "boundary", "expected_periods"),
    [
        (
            "hour",
            "2026-09-03T16:59:59.999999+00:00",
            "2026-09-03T17:00:00+00:00",
            ["2026-09-04T00", "2026-09-04T01"],
        ),
        (
            "day",
            "2026-09-30T15:59:59.999999+00:00",
            "2026-09-30T16:00:00+00:00",
            ["2026-09-30", "2026-10-01"],
        ),
        (
            "month",
            "2026-12-31T15:59:59.999999+00:00",
            "2026-12-31T16:00:00+00:00",
            ["2026-12", "2027-01"],
        ),
    ],
)
def test_taipei_buckets_preserve_microseconds_at_rollover(
    ledger, monkeypatch, group_by, bucket, before, boundary,
    expected_periods,
):
    with usage_scope(user_id="u1", project_id="p1"):
        for when, tokens in [(before, 2), (boundary, 4)]:
            _record_at(
                ledger, monkeypatch, when,
                provider="g", model="m", usage=LLMUsage(0, 0, tokens),
            )

    result = ledger.timeseries_usage(
        bucket=bucket, group_by=group_by, report_timezone="Asia/Taipei",
    )

    assert result["report_timezone"] == "Asia/Taipei"
    assert result["periods"] == expected_periods
    points = result["series"][0]["points"] if group_by else result["points"]
    assert [point["total_tokens"] for point in points] == [2, 4]
    assert [point["calls"] for point in points] == [1, 1]


def test_taipei_day_range_matches_summary_events_and_grouped_series(
    ledger, monkeypatch,
):
    events = [
        ("2026-09-02T15:59:59.999999+00:00", "outside", 100),
        ("2026-09-02T16:00:00+00:00", "p1", 2),
        ("2026-09-02T16:00:00.000001+00:00", "p2", 4),
        ("2026-09-03T15:59:59.999999+00:00", "p3", 8),
        ("2026-09-03T16:00:00+00:00", "outside", 200),
    ]
    for when, project, tokens in events:
        with usage_scope(user_id="u1", project_id=project):
            _record_at(
                ledger, monkeypatch, when,
                provider="g", model="m", usage=LLMUsage(0, 0, tokens),
            )
    filters = {
        "since": "2026-09-02T16:00:00+00:00",
        "until": "2026-09-03T16:00:00+00:00",
        "user_id": "u1",
    }

    summary = ledger.summarize_usage(**filters)
    detail = ledger.list_usage_events(**filters)
    assert summary["totals"]["total_tokens"] == 14
    assert summary["totals"]["calls"] == len(detail) == 3
    assert {row["created_at"] for row in detail} == {
        event[0] for event in events[1:4]
    }

    for group_by in ["", "project"]:
        result = ledger.timeseries_usage(
            bucket="day", group_by=group_by, limit=1,
            report_timezone="Asia/Taipei", **filters,
        )
        assert result["periods"] == ["2026-09-03"]
        points = (
            [point for series in result["series"] for point in series["points"]]
            if group_by else result["points"]
        )
        assert sum(point["calls"] for point in points) == 3
        assert sum(point["total_tokens"] for point in points) == 14
        if group_by:
            assert {series["project_id"] for series in result["series"]} == {
                "p3", "__other__",
            }


@pytest.mark.parametrize("report_timezone", ["Europe/London", "UTC+8", ""])
def test_timeseries_rejects_unsupported_report_timezone(ledger, report_timezone):
    with pytest.raises(ValueError, match="timezone"):
        ledger.timeseries_usage(report_timezone=report_timezone)


def test_ledger_write_failure_does_not_raise(ledger, monkeypatch):
    monkeypatch.setattr(ledger, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("disk")))
    assert ledger.record_usage_event(provider="g", model="m", usage=LLMUsage(1, 1, 2)) is None


def test_embed_principal_lands_in_the_ledger_row(ledger):
    with usage_scope(
        kind="chat",
        user_id="embed:ovk_abc",
        project_id="p1",
        principal_type="embed_key",
        principal_id="ovk_abc",
    ):
        ledger.record_usage_event(
            provider="openai", model="gpt", usage=LLMUsage(1, 2, 3),
        )

    events = ledger.list_usage_events(limit=10)
    assert events[0]["principal_type"] == "embed_key"
    assert events[0]["principal_id"] == "ovk_abc"


def test_ledger_filters_and_groups_by_principal(ledger):
    with usage_scope(principal_type="embed_key", principal_id="ovk_a", project_id="p"):
        ledger.record_usage_event(provider="o", model="m", usage=LLMUsage(1, 1, 2))
    with usage_scope(principal_type="user", principal_id="u1", project_id="p"):
        ledger.record_usage_event(provider="o", model="m", usage=LLMUsage(5, 5, 10))

    only_embed = ledger.summarize_usage(
        group_by="principal", principal_type="embed_key",
    )
    assert only_embed["totals"]["total_tokens"] == 2
    assert only_embed["groups"][0]["principal_id"] == "ovk_a"

    filtered_events = ledger.list_usage_events(limit=10, principal_id="u1")
    assert len(filtered_events) == 1
    assert filtered_events[0]["principal_id"] == "u1"


def test_ledger_adds_principal_columns_to_a_pre_existing_table(tmp_path):
    """既有帳本是用舊 schema 建的，新欄位必須靠 ALTER 補上。"""
    import sqlite3

    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'chat',
            user_id TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT '',
            project_id TEXT NOT NULL DEFAULT 'default',
            session_id TEXT NOT NULL DEFAULT '',
            persona_id TEXT NOT NULL DEFAULT 'default',
            trace_id TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            cached_tokens INTEGER NOT NULL DEFAULT 0,
            reasoning_tokens INTEGER NOT NULL DEFAULT 0,
            latency_ms REAL NOT NULL DEFAULT 0,
            raw TEXT
        );
        """
    )
    connection.commit()
    connection.close()

    usage_ledger.set_usage_db_path(path)
    try:
        with usage_scope(principal_type="embed_key", principal_id="ovk_x"):
            usage_ledger.record_usage_event(
                provider="o", model="m", usage=LLMUsage(1, 1, 2),
            )
        events = usage_ledger.list_usage_events(limit=5)
    finally:
        usage_ledger.set_usage_db_path(None)

    assert events[0]["principal_type"] == "embed_key"
    assert events[0]["principal_id"] == "ovk_x"


def test_scope_events_carry_timeline_offsets(ledger):
    """每筆事件都要帶請求時鐘上的起訖位移，前端才畫得出時間軸。"""
    with usage_scope(kind="chat", user_id="u1") as scope:
        usage_ledger.record_usage_event(
            provider="gemini",
            model="gemini-2.5-flash",
            usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            latency_ms=250.0,
        )
        summary = summarize_collected(scope)

    timeline = summary["timeline"]
    assert len(timeline) == 1
    entry = timeline[0]
    assert entry["model"] == "gemini-2.5-flash"
    # 這次呼叫的延遲（250ms）比 scope 已經歷的時間還長，起點應被釘在 0
    # 而不是變成負數。
    assert entry["started_at_ms"] == 0.0
    assert 0 < entry["ended_at_ms"] < 250.0


def test_timeline_offsets_reflect_latency_when_it_fits(ledger):
    """延遲落在 scope 存續時間內時，長條長度就等於該次呼叫的延遲。"""
    import time as _time

    with usage_scope(kind="chat") as scope:
        _time.sleep(0.05)
        usage_ledger.record_usage_event(
            provider="gemini", model="m", usage=None, latency_ms=20.0,
        )
        summary = summarize_collected(scope)

    entry = summary["timeline"][0]
    assert entry["started_at_ms"] > 0
    assert entry["ended_at_ms"] - entry["started_at_ms"] == pytest.approx(20.0, abs=1.0)


def test_ledger_row_has_no_timeline_columns(ledger):
    """位移只在 scope 鏡像裡，不寫進帳本：帳本存的是計費事實。"""
    with usage_scope(kind="chat") as scope:
        row = usage_ledger.record_usage_event(
            provider="gemini", model="m", usage=None, latency_ms=1.0,
        )
        assert row is not None
        assert "started_at_ms" not in row
        assert scope.collected[0]["started_at_ms"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("principal_type,principal_id", [
    ("user", "live-user"), ("embed_key", "live-key"),
])
async def test_live_close_usage_visible_only_to_its_owner(
    ledger, monkeypatch, principal_type, principal_id,
):
    from types import SimpleNamespace

    from live import gemini_live

    monkeypatch.setattr(gemini_live, "project_has_taiwanese_route", lambda _: False)
    session = gemini_live.GeminiLiveSession(
        relay_session_id="relay-ledger", client_id="client-ledger",
        user_id="live-user", principal_type=principal_type,
        principal_id=principal_id,
        config=SimpleNamespace(live_gemini_model="test-live"),
    )
    session._input_audio_seconds = 1.0
    session._output_audio_seconds = 2.0
    await session.close()
    await session.close()

    events = ledger.list_usage_events(
        user_id="live-user", principal_type=principal_type, principal_id=principal_id,
    )
    assert len(events) == 2
    assert sum(event["units"] for event in events) == 3.0
    assert all(event["unit_type"] == "seconds" for event in events)
    assert ledger.list_usage_events(user_id="someone-else") == []
    assert ledger.list_usage_events(principal_id="another-key") == []

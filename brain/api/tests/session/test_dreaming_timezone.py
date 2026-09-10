"""Dreaming calendar boundaries and dates persisted by real phase execution."""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def dreaming(monkeypatch, tmp_path):
    modules = {
        name: importlib.import_module(f"memory.dreaming.{name}")
        for name in ("paths", "scheduler", "light_phase", "deep_phase", "rem_phase")
    }
    settings = SimpleNamespace(
        dreaming_timezone="Asia/Taipei",
        dreaming_lookback_days=1,
        dreaming_candidate_limit=100,
        dreaming_min_score=0,
        dreaming_min_recall_count=0,
        dreaming_min_unique_queries=0,
        dreaming_similarity_threshold=0.9,
    )
    clock = SimpleNamespace(now=datetime(2026, 9, 9, 19, tzinfo=timezone.utc))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now.astimezone(tz) if tz else clock.now.replace(tzinfo=None)

    for name, module in modules.items():
        monkeypatch.setattr(module, "get_settings", lambda: settings)
        if hasattr(module, "get_workspace_root"):
            monkeypatch.setattr(module, "get_workspace_root", lambda pid: tmp_path)
        if hasattr(module, "datetime"):
            monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setattr(modules["scheduler"], "_last_run", {})
    monkeypatch.setattr(modules["scheduler"], "rotate_traces", lambda pid: 0)
    table = MagicMock()
    deep = modules["deep_phase"]
    monkeypatch.setattr(deep, "get_memories_table", lambda pid: table)
    monkeypatch.setattr(deep, "_dedup_against_memories", lambda rows, *args: rows)
    monkeypatch.setattr(deep, "normalize_vector", lambda vec: vec)
    embedder = SimpleNamespace(encode=lambda texts: [[1.0, 0.0] for _ in texts])
    for name in ("deep_phase", "rem_phase"):
        monkeypatch.setattr(modules[name], "get_embedder", lambda: embedder)
    traces = [{"query": query, "results": []} for query in ("one", "two", "three")]
    for name in ("light_phase", "rem_phase"):
        monkeypatch.setattr(modules[name], "read_traces", lambda *args, **kwargs: traces)
    monkeypatch.setattr(
        modules["light_phase"], "score_importance", lambda text: SimpleNamespace(score=1),
    )
    return SimpleNamespace(
        **modules, settings=settings, clock=clock, root=tmp_path, table=table,
    )


@pytest.mark.parametrize(
    ("zone", "completed_at", "now", "expected"),
    [
        ("Asia/Taipei", "2026-09-09T19:00:00+00:00", "2026-09-09T19:01:00+00:00", True),
        ("Asia/Taipei", "2026-09-09T19:00:00", "2026-09-09T19:01:00+00:00", True),
        ("Asia/Taipei", "2026-09-09T19:00:00Z", "2026-09-10T16:00:00+00:00", False),
        ("UTC-5", "2026-09-10T04:00:00+00:00", "2026-09-10T04:01:00+00:00", True),
        ("UTC-5", "2026-09-10T04:00:00+00:00", "2026-09-10T05:00:00+00:00", False),
        ("America/New_York", "2026-03-08T06:30:00+00:00", "2026-03-08T07:30:00+00:00", True),
        ("America/New_York", "2026-11-01T05:30:00+00:00", "2026-11-01T06:30:00+00:00", True),
        ("America/New_York", "2026-07-01T03:59:59+00:00", "2026-07-01T04:00:00+00:00", False),
        ("Asia/Taipei", "invalid", "2026-09-09T19:00:00+00:00", False),
        ("Asia/Taipei", None, "2026-09-09T19:00:00+00:00", False),
    ],
)
def test_already_ran_uses_local_completion_date(
    dreaming, zone, completed_at, now, expected,
):
    dreaming.clock.now = datetime.fromisoformat(now)
    dreaming.scheduler._last_run["p1"] = {
        "status": "ok", "completed_at": completed_at,
    }
    tz = dreaming.paths.resolve_timezone(zone)
    assert dreaming.scheduler._already_ran_today("p1", tz) is expected


def test_taipei_three_am_skips_retries_allows_force_and_next_day(dreaming):
    dreaming.scheduler._last_run["p1"] = {
        "status": "ok", "completed_at": "2026-09-09T19:00:00+00:00",
    }
    dreaming.clock.now += timedelta(minutes=1)
    assert dreaming.scheduler.run_dreaming_cycle("p1")["status"] == "skipped"
    assert dreaming.scheduler.run_dreaming_cycle("p1", force=True)["status"] == "ok"
    dreaming.clock.now += timedelta(days=1)
    assert dreaming.scheduler.run_dreaming_cycle("p1")["status"] == "ok"


def _write_daily(root, day, text):
    directory = root / "memory" / "default"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{day}.md").write_text(f"### Summary\n{text}\n", encoding="utf-8")


def _assert_phase_dates(dreaming, day, time):
    for phase in ("light", "deep", "rem"):
        reports = list((dreaming.root / "dreaming" / phase).glob("*.md"))
        assert [path.name for path in reports] == [f"{day}.md"]
        heading = reports[0].read_text(encoding="utf-8").splitlines()[0]
        assert day in heading
        if phase != "deep":
            assert time in heading
    records = dreaming.table.add.call_args.args[0]
    assert records and all(record["date"] == day for record in records)


@pytest.mark.parametrize(
    ("zone", "now", "day", "time"),
    [
        ("Asia/Taipei", "2026-09-09T19:00:00+00:00", "2026-09-10", "03:00:00"),
        ("UTC-5", "2026-09-10T04:00:00+00:00", "2026-09-09", "23:00:00"),
        ("America/New_York", "2026-07-01T04:30:00+00:00", "2026-07-01", "00:30:00"),
        ("America/New_York", "2026-01-01T04:30:00+00:00", "2025-12-31", "23:30:00"),
    ],
)
def test_direct_phases_default_to_configured_calendar(dreaming, zone, now, day, time):
    dreaming.settings.dreaming_timezone = zone
    dreaming.clock.now = datetime.fromisoformat(now)
    local_day = datetime.fromisoformat(day).date()
    _write_daily(dreaming.root, day, "current memory")
    _write_daily(dreaming.root, str(local_day - timedelta(days=1)), "boundary memory")
    _write_daily(dreaming.root, str(local_day - timedelta(days=2)), "expired memory")

    result = dreaming.light_phase.run_light_phase("p1")
    assert result["fragment_count"] == 2
    assert dreaming.deep_phase.run_deep_phase("p1")["promoted_count"] == 2
    assert dreaming.rem_phase.run_rem_phase("p1")["theme_count"] > 0
    _assert_phase_dates(dreaming, day, time)
    report = dreaming.paths.write_dreaming_report("p1", "direct", ["report"])
    assert report.name == f"{day}.md"


def test_cycle_crossing_midnight_keeps_all_phase_artifacts_on_start_day(
    dreaming, monkeypatch,
):
    dreaming.clock.now = datetime(2026, 12, 31, 15, 59, 59, tzinfo=timezone.utc)
    _write_daily(dreaming.root, "2026-12-30", "memory at lookback boundary")

    def cross_midnight(project_id):
        dreaming.clock.now += timedelta(seconds=2)
        return 0

    monkeypatch.setattr(dreaming.scheduler, "rotate_traces", cross_midnight)
    result = dreaming.scheduler.run_dreaming_cycle("p1", force=True)
    assert result["status"] == "ok"
    assert result["light"]["fragment_count"] == 1
    assert result["deep"]["promoted_count"] == 1
    assert result["started_at"] == "2026-12-31T15:59:59+00:00"
    assert result["completed_at"] == "2026-12-31T16:00:01+00:00"
    _assert_phase_dates(dreaming, "2026-12-31", "23:59:59")

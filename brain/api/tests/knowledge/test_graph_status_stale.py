"""A 'building' status whose background task was lost must not trap the UI.

If the rebuild process restarts mid-build, status.json stays "building"
forever and the frontend polls it indefinitely. ``load_project_status`` demotes
such an orphaned status to "failed" once it is older than the stale threshold,
so callers offer a rebuild instead of an endless spinner.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from knowledge.graph import STALE_BUILDING_SECONDS, _demote_if_stale


def _iso(delta_seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=delta_seconds)).isoformat()


def test_fresh_building_is_left_alone():
    status = {"state": "building", "project_id": "p", "started_at": _iso(10)}
    assert _demote_if_stale(status) == status


def test_stale_building_is_demoted_to_failed():
    status = {
        "state": "building",
        "project_id": "p",
        "started_at": _iso(STALE_BUILDING_SECONDS + 60),
    }
    out = _demote_if_stale(status)
    assert out["state"] == "failed"
    assert out["stale"] is True
    assert out["error"]
    assert out["started_at"] == status["started_at"]


def test_ready_status_is_never_touched():
    status = {"state": "ready", "project_id": "p", "started_at": _iso(99999)}
    assert _demote_if_stale(status) == status


def test_building_without_started_at_is_left_alone():
    status = {"state": "building", "project_id": "p"}
    assert _demote_if_stale(status) == status


def test_building_with_unparseable_started_at_is_left_alone():
    status = {"state": "building", "project_id": "p", "started_at": "not-a-date"}
    assert _demote_if_stale(status) == status

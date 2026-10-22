"""HTTP surface of the usage ledger (internal token gated)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from core.usage import LLMUsage, usage_scope  # noqa: E402
from infra import usage_ledger  # noqa: E402
from routes.usage import router  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path):
    usage_ledger.set_usage_db_path(tmp_path / "usage.db")
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    usage_ledger.set_usage_db_path(None)


def test_usage_routes_require_internal_token(client: TestClient):
    assert client.get("/brain/usage/summary").status_code == 403
    assert client.get("/brain/usage/events").status_code == 403
    assert client.get("/brain/usage/timeseries").status_code == 403


def test_usage_summary_and_events(client: TestClient):
    headers = {"X-Internal-Token": "test-internal-token"}
    with usage_scope(user_id="u1", project_id="p1", trace_id="t1"):
        usage_ledger.record_usage_event(provider="g", model="m", usage=LLMUsage(2, 3, 5))

    summary = client.get("/brain/usage/summary", params={"user_id": "u1"}, headers=headers)
    assert summary.status_code == 200
    assert summary.json()["totals"]["total_tokens"] == 5
    assert summary.json()["groups"][0]["model"] == "m"

    events = client.get("/brain/usage/events", params={"trace_id": "t1"}, headers=headers)
    assert events.status_code == 200
    assert events.json()["count"] == 1
    assert events.json()["events"][0]["output_tokens"] == 3

    bad = client.get("/brain/usage/summary", params={"group_by": "nope"}, headers=headers)
    assert bad.status_code == 400


def test_repeated_project_ids_reach_every_query(client: TestClient):
    headers = {"X-Internal-Token": "test-internal-token"}
    for project_id in ("p1", "p2", "p3"):
        with usage_scope(user_id="u", project_id=project_id):
            usage_ledger.record_usage_event(provider="g", model="m", usage=LLMUsage(1, 1, 2))
    params = [("project_ids", "p1"), ("project_ids", "p2")]

    summary = client.get("/brain/usage/summary", params=params, headers=headers)
    events = client.get("/brain/usage/events", params=params, headers=headers)
    series = client.get("/brain/usage/timeseries", params=params, headers=headers)

    assert summary.json()["totals"]["total_tokens"] == 4
    assert events.json()["count"] == 2
    assert series.status_code == 200
    assert sum(point["total_tokens"] for point in series.json()["points"]) == 4


def test_api_key_usage_is_separate_per_key_and_rolls_up_to_owner(client):
    headers = {"X-Internal-Token": "test-internal-token"}
    for key_id, seconds in [("key-a", 1.5), ("key-b", 2.5)]:
        response = client.post(
            "/brain/usage/events", headers=headers,
            json={
                "provider": "breeze", "kind": "asr",
                "unit_type": "seconds", "units": seconds,
                "user_id": "owner-1", "role": "admin",
                "principal_type": "api_key", "principal_id": key_id,
            },
        )
        assert response.status_code == 201
    with usage_scope(
        user_id="owner-1", principal_type="user", principal_id="owner-1",
    ):
        usage_ledger.record_usage_event(
            provider="g", model="m", usage=LLMUsage(2, 3, 5),
        )

    owner = client.get(
        "/brain/usage/summary", headers=headers,
        params={"user_id": "owner-1", "group_by": "principal"},
    ).json()
    assert owner["totals"]["calls"] == 3
    assert owner["totals"]["seconds"] == 4
    assert {
        (row["principal_type"], row["principal_id"])
        for row in owner["groups"]
    } == {("api_key", "key-a"), ("api_key", "key-b"), ("user", "owner-1")}

    filters = {
        "user_id": "owner-1", "principal_type": "api_key",
        "principal_id": "key-b",
    }
    summary = client.get(
        "/brain/usage/summary", headers=headers, params=filters,
    ).json()
    assert summary["totals"]["calls"] == 1
    assert summary["totals"]["seconds"] == 2.5
    events = client.get(
        "/brain/usage/events", headers=headers, params=filters,
    ).json()
    assert events["count"] == 1
    assert events["events"][0]["user_id"] == "owner-1"
    assert events["events"][0]["principal_id"] == "key-b"
    series = client.get(
        "/brain/usage/timeseries", headers=headers, params=filters,
    ).json()
    assert sum(point["calls"] for point in series["points"]) == 1
    assert client.get(
        "/brain/usage/events", headers=headers,
        params={**filters, "user_id": "different-owner"},
    ).json()["count"] == 0


@pytest.mark.parametrize("group_by", ["", "project"])
def test_timeseries_report_timezone_and_range(client, monkeypatch, group_by):
    headers = {"X-Internal-Token": "test-internal-token"}
    with usage_scope(user_id="u1", project_id="p1"):
        for when, tokens in [
            ("2026-12-31T15:59:59.999999+00:00", 100),
            ("2026-12-31T16:00:00+00:00", 2),
            ("2027-01-01T15:59:59.999999+00:00", 4),
            ("2027-01-01T16:00:00+00:00", 200),
        ]:
            monkeypatch.setattr(usage_ledger, "_now_iso", lambda: when)
            usage_ledger.record_usage_event(
                provider="g", model="m", usage=LLMUsage(0, 0, tokens),
            )
    filters = {
        "since": "2026-12-31T16:00:00+00:00",
        "until": "2027-01-01T16:00:00+00:00",
        "user_id": "u1",
    }

    response = client.get(
        "/brain/usage/timeseries",
        params={
            **filters, "bucket": "day", "group_by": group_by,
            "report_timezone": "Asia/Taipei",
        },
        headers=headers,
    )
    assert response.status_code == 200
    result = response.json()
    assert result["report_timezone"] == "Asia/Taipei"
    assert result["periods"] == ["2027-01-01"]
    points = result["series"][0]["points"] if group_by else result["points"]
    assert points[0]["total_tokens"] == 6
    assert points[0]["calls"] == 2

    summary = client.get(
        "/brain/usage/summary", params=filters, headers=headers,
    )
    events = client.get(
        "/brain/usage/events", params=filters, headers=headers,
    )
    assert summary.status_code == events.status_code == 200
    assert summary.json()["totals"]["total_tokens"] == 6
    assert events.json()["count"] == 2
    assert sum(row["total_tokens"] for row in events.json()["events"]) == 6


def test_timeseries_defaults_to_utc(client, monkeypatch):
    headers = {"X-Internal-Token": "test-internal-token"}
    monkeypatch.setattr(
        usage_ledger, "_now_iso", lambda: "2026-12-31T16:00:00+00:00",
    )
    usage_ledger.record_usage_event(
        provider="g", model="m", usage=LLMUsage(1, 1, 2),
    )
    response = client.get("/brain/usage/timeseries", headers=headers)
    explicit = client.get(
        "/brain/usage/timeseries", params={"report_timezone": "UTC"},
        headers=headers,
    )
    assert response.status_code == explicit.status_code == 200
    assert response.json() == explicit.json()
    assert response.json()["report_timezone"] == "UTC"
    assert response.json()["periods"] == ["2026-12-31"]


@pytest.mark.parametrize("report_timezone", ["Europe/London", "UTC+8", ""])
def test_timeseries_rejects_invalid_timezone(client, report_timezone):
    response = client.get(
        "/brain/usage/timeseries",
        params={"report_timezone": report_timezone},
        headers={"X-Internal-Token": "test-internal-token"},
    )
    assert response.status_code == 400
    assert "timezone" in response.json()["detail"]

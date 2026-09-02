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

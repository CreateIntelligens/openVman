from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client() -> TestClient:
    from config import get_settings
    from routes.backups import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, headers={"X-Internal-Token": get_settings().gateway_internal_token})


def test_backup_endpoint_passes_dry_run_and_reports_conflict(monkeypatch):
    from memory.session_backup import BackupInProgressError
    from routes import backups

    calls = []

    def fake_run(*, dry_run=False):
        calls.append(dry_run)
        if len(calls) > 1:
            raise BackupInProgressError("已有備份正在執行")
        return {"backup_id": "x", "dry_run": dry_run}

    monkeypatch.setattr(backups, "run_backup", fake_run)
    with _client() as client:
        first = client.post("/brain/backups/sessions", json={"dry_run": True})
        second = client.post("/brain/backups/sessions", json={})

    assert first.json() == {"backup_id": "x", "dry_run": True}
    assert second.status_code == 409
    assert calls == [True, False]


def test_backup_endpoint_requires_internal_token():
    from routes.backups import router

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/brain/backups/sessions").status_code in {401, 403}

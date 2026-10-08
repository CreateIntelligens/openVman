from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from internal_routes import router


def test_internal_decision_requires_internal_token(monkeypatch):
    import safety.internal_auth as auth

    monkeypatch.setattr(auth, "get_settings", lambda: type("Config", (), {"gateway_internal_token": "secret"})())
    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        response = client.post("/internal/decision", json={
            "state": "hello",
            "questions": {"q": {"type": "noul", "instructions": "?"}},
            "purpose": "test",
            "timeout_seconds": 1,
        })

    assert response.status_code == 403


def test_internal_decision_returns_normalized_answer(monkeypatch):
    import core.decision_router as decision_router
    import safety.internal_auth as auth

    monkeypatch.setattr(auth, "get_settings", lambda: type("Config", (), {"gateway_internal_token": "secret"})())
    monkeypatch.setattr(
        decision_router,
        "decide",
        lambda *args, **kwargs: decision_router.DecisionResult(
            {"q": {"type": "choice", "choice": "STOP", "confidence": 0.9}},
            provider="jev",
            hop_id="jev",
            model="jev-latest",
        ),
    )
    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        response = client.post(
            "/internal/decision",
            headers={"X-Internal-Token": "secret"},
            json={
                "state": "new question",
                "questions": {"q": {"type": "choice", "criteria": {"STOP": "stop", "IGNORE": "ignore"}}},
                "purpose": "interrupt",
                "timeout_seconds": 0.6,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "answers": {"q": {"type": "choice", "choice": "STOP", "confidence": 0.9}},
        "provider": "jev",
        "hop_id": "jev",
        "model": "jev-latest",
    }

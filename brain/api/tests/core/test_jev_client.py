"""The legacy Jev facade delegates to the shared decision broker."""

from __future__ import annotations

from core import jev_client


def test_jev_noul_delegates_to_shared_broker(monkeypatch):
    calls = []

    def decide(state, question, *, timeout, purpose):
        calls.append((state, question, timeout, purpose))
        return 0.8

    monkeypatch.setattr("core.decision_router.decide_noul", decide)

    assert jev_client.jev_noul("state", {"instructions": "?"}, timeout=1.5, purpose="gate") == 0.8
    assert calls == [("state", {"instructions": "?"}, 1.5, "gate")]


def test_jev_available_reports_shared_provider_availability(monkeypatch):
    monkeypatch.setattr("core.decision_router.decision_available", lambda: True)
    assert jev_client.jev_available() is True

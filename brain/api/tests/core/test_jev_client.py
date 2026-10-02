"""Every Jev call is counted in usage.db under its purpose."""

from __future__ import annotations

import httpx
import pytest

from core import jev_client


@pytest.fixture
def recorded(monkeypatch):
    events: list[dict] = []
    monkeypatch.setattr(
        "infra.usage_ledger.record_usage_event", lambda **kw: events.append(kw),
    )
    return events


def _respond(monkeypatch, handler):
    monkeypatch.setattr(jev_client.httpx, "post", handler)


def test_successful_call_is_recorded_with_tokens(monkeypatch, recorded):
    request = httpx.Request("POST", "https://jev")
    _respond(monkeypatch, lambda *a, **kw: httpx.Response(200, request=request, json={
        "model": "jev-1", "usage": {"input_tokens": 30, "output_tokens": 2},
        "answers": {"q": {"noul": 0.8}},
    }))

    assert jev_client.jev_noul("state", {"instructions": "?"}, timeout=1, purpose="memory_gate") == 0.8

    [event] = recorded
    assert event["kind"] == "jev_memory_gate"
    assert event["provider"] == "typesafe" and event["model"] == "jev-1"
    assert event["usage"].total_tokens == 32
    assert event["raw"] == {"status": "ok", "questions": 1}


def test_failed_call_is_still_counted(monkeypatch, recorded):
    def timeout(*a, **kw):
        raise httpx.ReadTimeout("slow")

    _respond(monkeypatch, timeout)
    with pytest.raises(httpx.ReadTimeout):
        jev_client.jev_nouls("state", {"a": {}, "b": {}}, timeout=1, purpose="language")

    [event] = recorded
    assert event["kind"] == "jev_language"
    assert event["raw"] == {"status": "timeout", "questions": 2}

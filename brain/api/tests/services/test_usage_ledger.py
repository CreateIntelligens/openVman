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


def test_ledger_write_failure_does_not_raise(ledger, monkeypatch):
    monkeypatch.setattr(ledger, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("disk")))
    assert ledger.record_usage_event(provider="g", model="m", usage=LLMUsage(1, 1, 2)) is None

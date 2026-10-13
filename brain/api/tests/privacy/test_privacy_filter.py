"""Personal-data check on what the user typed."""

from __future__ import annotations

import logging

import pytest

import privacy.filter as privacy_filter
from privacy.cache import PrivacyFilterCache


class _Settings:
    privacy_filter_enabled = True
    privacy_filter_cache_size = 8
    resolved_privacy_filter_block_categories = ["secret"]


@pytest.fixture
def detector(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    result: dict[str, object] = {"value": {}}

    def fake_detect(text: str):
        calls.append(text)
        return result["value"]

    monkeypatch.setattr(privacy_filter, "get_settings", lambda: _Settings())
    monkeypatch.setattr(privacy_filter, "detect_pii", fake_detect)
    cache = PrivacyFilterCache(8)
    monkeypatch.setattr(privacy_filter, "get_privacy_filter_cache", lambda size: cache)
    events: list[object] = []
    monkeypatch.setattr(privacy_filter, "record_privacy_filter_event", events.append)
    return calls, result, events


def test_reports_detected_categories_in_order(detector) -> None:
    calls, result, events = detector
    result["value"] = {"private_phone": 1, "private_email": 1}

    report = privacy_filter.scan_text_for_pii("找我 0912345678 或 a@b.com", trace_id="t1")

    assert report is not None
    assert report.categories == ("private_email", "private_phone")
    assert report.counts == {"private_email": 1, "private_phone": 1}
    assert [event.action for event in events] == ["detected"]
    assert events[0].trace_id == "t1"


def test_same_text_is_asked_once(detector) -> None:
    calls, result, _ = detector
    result["value"] = {"private_person": 1}

    privacy_filter.scan_text_for_pii("我叫王小明")
    privacy_filter.scan_text_for_pii("我叫王小明")

    assert calls == ["我叫王小明"]


def test_skipped_scan_is_not_cached_and_reports_nothing(detector) -> None:
    # Clef 忙或失敗時回 None：不能記成「沒有個資」，下次同一句要重問。
    calls, result, events = detector
    result["value"] = None

    assert privacy_filter.scan_text_for_pii("我叫王小明") is None
    assert privacy_filter.scan_text_for_pii("我叫王小明") is None
    assert len(calls) == 2
    assert [event.action for event in events] == ["skipped", "skipped"]


def test_clean_text_gives_an_empty_report(detector) -> None:
    _, result, events = detector
    result["value"] = {}

    report = privacy_filter.scan_text_for_pii("請問要怎麼掛號？")

    assert report is not None and report.counts == {}
    assert events == []


def test_disabled_filter_does_not_ask(detector, monkeypatch: pytest.MonkeyPatch) -> None:
    calls, _, _ = detector
    settings = _Settings()
    settings.privacy_filter_enabled = False
    monkeypatch.setattr(privacy_filter, "get_settings", lambda: settings)

    assert privacy_filter.scan_text_for_pii("我叫王小明") is None
    assert calls == []


def test_blocked_category_logs_without_raw_text(detector, caplog: pytest.LogCaptureFixture) -> None:
    _, result, _ = detector
    result["value"] = {"secret": 1}

    with caplog.at_level(logging.WARNING):
        privacy_filter.scan_text_for_pii("密碼是Abc12345")

    assert "category=secret" in caplog.text
    assert "Abc12345" not in caplog.text

"""Tests for outbound LLM message sanitization."""

from __future__ import annotations

import logging

import pytest

from privacy.exceptions import PrivacyViolationError
from privacy.filter import detect_llm_messages_pii
from privacy.model import enable_stub_detector_for_tests


class _Settings:
    privacy_filter_enabled = True
    privacy_filter_include_system = False
    privacy_filter_cache_size = 8
    privacy_filter_block_categories = "secret"

    @property
    def resolved_privacy_filter_block_categories(self) -> list[str]:
        return [item.strip() for item in self.privacy_filter_block_categories.split(",") if item.strip()]


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> _Settings:
    settings = _Settings()
    for key, value in overrides.items():
        setattr(settings, key, value)

    import privacy.filter as privacy_filter

    monkeypatch.setattr(privacy_filter, "get_settings", lambda: settings)
    enable_stub_detector_for_tests()
    return settings


def test_detect_reports_user_and_tool_roles_without_mutating_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)
    messages = [
        {"role": "user", "content": "Call 0912345678"},
        {"role": "tool", "content": "owner jane@example.com"},
    ]

    report = detect_llm_messages_pii(
        messages,
        source="chat",
        trace_id="t1",
    )

    assert report is not None
    assert messages == [
        {"role": "user", "content": "Call 0912345678"},
        {"role": "tool", "content": "owner jane@example.com"},
    ]
    assert report.categories == ("private_email", "private_phone")
    assert report.counts == {"private_email": 1, "private_phone": 1}
    assert report.per_message == (
        {"private_phone": 1},
        {"private_email": 1},
    )


def test_detect_skips_system_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)
    message = {"role": "system", "content": "System phone 0912345678"}

    report = detect_llm_messages_pii([message], source="chat", trace_id="t1")

    assert report is not None
    assert report.counts == {}
    assert report.per_message == ({},)


def test_detect_includes_system_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, privacy_filter_include_system=True)

    report = detect_llm_messages_pii(
        [{"role": "system", "content": "System phone 0912345678"}],
        source="chat",
        trace_id="t1",
    )

    assert report is not None
    assert report.counts == {"private_phone": 1}
    assert report.per_message == ({"private_phone": 1},)


def test_detect_blocks_configured_secret_category(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)

    with pytest.raises(PrivacyViolationError):
        detect_llm_messages_pii(
            [{"role": "user", "content": "password=super-secret"}],
            source="chat",
            trace_id="t1",
        )


def test_detect_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, privacy_filter_enabled=False)
    messages = [{"role": "user", "content": "Call 0912345678"}]

    assert detect_llm_messages_pii(messages, source="chat", trace_id="t1") is None


def test_audit_log_never_contains_raw_pii(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    _patch_settings(monkeypatch)
    caplog.set_level(logging.INFO, logger="brain")

    detect_llm_messages_pii(
        [{"role": "user", "content": "Call 0912345678"}],
        source="chat",
        trace_id="t1",
    )

    log_output = "\n".join(record.getMessage() for record in caplog.records)
    assert "0912345678" not in log_output
    assert "Call [REDACTED:private_phone]" not in log_output

"""Tests for outbound LLM message sanitization."""

from __future__ import annotations

import logging

import pytest

from privacy.exceptions import PrivacyViolationError
from privacy.filter import sanitize_llm_messages
from privacy.model import enable_regex_detector_for_tests


class _Settings:
    privacy_filter_enabled = True
    privacy_filter_mode = "mask"
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
    enable_regex_detector_for_tests()
    return settings


def test_sanitize_filters_user_and_tool_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)

    sanitized = sanitize_llm_messages(
        [
            {"role": "user", "content": "Call 0912345678"},
            {"role": "tool", "content": "owner jane@example.com"},
        ],
        source="chat",
        trace_id="t1",
    )

    assert sanitized[0]["content"] == "Call [REDACTED:private_phone]"
    assert sanitized[1]["content"] == "owner [REDACTED:private_email]"


def test_sanitize_skips_system_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)
    message = {"role": "system", "content": "System phone 0912345678"}

    sanitized = sanitize_llm_messages([message], source="chat", trace_id="t1")

    assert sanitized == [message]


def test_sanitize_filters_system_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, privacy_filter_include_system=True)

    sanitized = sanitize_llm_messages(
        [{"role": "system", "content": "System phone 0912345678"}],
        source="chat",
        trace_id="t1",
    )

    assert sanitized[0]["content"] == "System phone [REDACTED:private_phone]"


def test_sanitize_blocks_configured_secret_category(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)

    with pytest.raises(PrivacyViolationError):
        sanitize_llm_messages(
            [{"role": "user", "content": "password=super-secret"}],
            source="chat",
            trace_id="t1",
        )


def test_sanitize_disabled_returns_original_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, privacy_filter_enabled=False)
    messages = [{"role": "user", "content": "Call 0912345678"}]

    assert sanitize_llm_messages(messages, source="chat", trace_id="t1") is messages


def test_audit_log_never_contains_raw_pii(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    _patch_settings(monkeypatch)
    caplog.set_level(logging.INFO, logger="brain")

    sanitize_llm_messages(
        [{"role": "user", "content": "Call 0912345678"}],
        source="chat",
        trace_id="t1",
    )

    log_output = "\n".join(record.getMessage() for record in caplog.records)
    assert "0912345678" not in log_output
    assert "Call [REDACTED:private_phone]" not in log_output

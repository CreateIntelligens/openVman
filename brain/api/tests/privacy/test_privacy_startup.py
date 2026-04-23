"""Tests for privacy filter startup degradation."""

from __future__ import annotations

import pytest

from privacy.filter import sanitize_llm_messages
from privacy.model import disable_privacy_filter, enable_regex_detector_for_tests


class _Settings:
    privacy_filter_enabled = True
    privacy_filter_mode = "mask"
    privacy_filter_include_system = False
    privacy_filter_cache_size = 8
    privacy_filter_block_categories = "secret"

    @property
    def resolved_privacy_filter_block_categories(self) -> list[str]:
        return ["secret"]


def test_model_load_failure_flag_passes_messages_through(monkeypatch) -> None:
    import privacy.filter as privacy_filter

    monkeypatch.setattr(privacy_filter, "get_settings", lambda: _Settings())
    disable_privacy_filter("load failed")

    messages = [{"role": "user", "content": "Call 0912345678"}]
    assert sanitize_llm_messages(messages, source="chat", trace_id="t1") is messages


@pytest.mark.asyncio
async def test_startup_model_load_failure_disables_filter(monkeypatch) -> None:
    enable_regex_detector_for_tests()

    import main
    import privacy.filter as privacy_filter
    import privacy.model as privacy_model

    monkeypatch.setattr(main, "get_settings", lambda: _Settings())
    monkeypatch.setattr(privacy_filter, "get_settings", lambda: _Settings())
    monkeypatch.setattr(privacy_model, "load_privacy_filter_model", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    await main.load_privacy_filter_if_enabled()

    messages = [{"role": "user", "content": "Call 0912345678"}]
    assert sanitize_llm_messages(messages, source="chat", trace_id="t1") is messages

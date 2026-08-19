"""Tests for Gemini TTS configuration loading."""

from __future__ import annotations

import pytest

from app.config import TTSRouterConfig


def test_gemini_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # 測的是欄位預設值，必須擋掉真實環境變數（容器內 .env 有設這個 URL）。
    monkeypatch.delenv("TTS_GEMINI_URL", raising=False)

    config = TTSRouterConfig(_env_file=None)

    assert config.tts_gemini_url == ""

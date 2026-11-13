"""Gemini Decisions in front of the slow audio language model."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import config
from core.gemini_credentials import GeminiCredential
from memory import audio_language_decision as decision
from memory import language_detect

CREDENTIAL = GeminiCredential("key", "shared", "gemini", True)


# 分數取自 2026-11-13 實測的實際音檔。
@pytest.mark.parametrize(("scores", "expected"), [
    ({"zh": 0.86, "ko": 0.89, "ja": 0.13, "en": 0.02, "es": 0.05}, "zh"),
    ({"zh": 0.14, "ko": 0.18, "ja": 0.13, "en": 0.09, "es": 0.11}, "nan"),
    ({"zh": 0.15, "ko": 0.15, "ja": 0.13, "en": 0.40, "es": 0.16}, "nan"),
    ({"zh": 0.42, "ko": 0.30, "ja": 0.29, "en": 0.79, "es": 0.24}, "en"),
    ({"zh": 0.24, "ko": 0.09, "ja": 0.05, "en": 0.02, "es": 0.91}, "es"),
    # 真人台語常被聽成韓語、日語，日韓分數高時沒把握。
    ({"zh": 0.11, "ko": 0.88, "ja": 0.08, "en": 0.09, "es": 0.12}, None),
    ({"zh": 0.06, "ko": 0.77, "ja": 0.89, "en": 0.04, "es": 0.07}, None),
    # 華語分數卡在中間，也交給原本的模型。
    ({"zh": 0.76, "ko": 0.59, "ja": 0.13, "en": 0.10, "es": 0.11}, None),
])
def test_verdict_only_answers_when_sure(scores, expected):
    assert decision.verdict(scores) == expected


def _settings(monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(
        audio_language_decision_enabled=enabled,
        audio_language_decision_model="gemini-decision-1",
        audio_language_decision_timeout_seconds=2.0,
    ))


@pytest.mark.asyncio
async def test_disabled_only_asks_the_slow_model(monkeypatch):
    _settings(monkeypatch, False)
    monkeypatch.setattr(decision, "ask_decisions", lambda *a: pytest.fail("should not ask"))
    monkeypatch.setattr(language_detect, "detect_audio_language", lambda wav, **kw: "nan")
    assert await decision.detect_audio_language_async(b"RIFF") == "nan"


@pytest.mark.asyncio
async def test_sure_decision_does_not_wait_for_the_slow_model(monkeypatch):
    _settings(monkeypatch, True)
    release = threading.Event()
    monkeypatch.setattr(decision, "ask_decisions", lambda wav, cred: {
        "zh": 0.1, "en": 0.1, "es": 0.1, "ja": 0.1, "ko": 0.1,
    })

    def slow(wav, **kwargs):
        release.wait(5)
        return "zh"

    monkeypatch.setattr(language_detect, "detect_audio_language", slow)
    try:
        assert await decision.detect_audio_language_async(b"RIFF", credential=CREDENTIAL) == "nan"
    finally:
        release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("decisions", [
    lambda wav, cred: {"zh": 0.1, "en": 0.1, "es": 0.1, "ja": 0.9, "ko": 0.1},
    lambda wav, cred: (_ for _ in ()).throw(RuntimeError("down")),
])
async def test_unsure_or_failed_decision_waits_for_the_slow_model(monkeypatch, decisions):
    _settings(monkeypatch, True)
    monkeypatch.setattr(decision, "ask_decisions", decisions)
    monkeypatch.setattr(language_detect, "detect_audio_language", lambda wav, **kw: "zh")
    assert await decision.detect_audio_language_async(b"RIFF", credential=CREDENTIAL) == "zh"

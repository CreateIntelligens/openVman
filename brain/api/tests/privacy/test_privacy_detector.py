"""Clef answers which kinds of personal data a message contains."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import privacy.detector as detector


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch):
    cfg = SimpleNamespace(privacy_clef_timeout_seconds=3.0, privacy_max_inflight=1)
    monkeypatch.setattr(detector, "get_settings", lambda: cfg)
    monkeypatch.setattr(detector, "_inflight", None)
    return cfg


def _answers(**scores: float):
    return SimpleNamespace(answers={k: {"noul": v} for k, v in scores.items()})


def test_only_clef_is_asked(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    # Jev 與 OpenAI 是外部服務：查個資不能把個資送出去，連備援都不行。
    seen = {}

    def fake_decide(state, questions, **kwargs):
        seen.update(kwargs, state=state, questions=questions)
        return _answers(private_person=0.9, private_phone=0.2)

    monkeypatch.setattr(detector, "decide", fake_decide)

    assert detector.detect_pii("我叫王小明") == {"private_person": 1}
    assert seen["providers"] == frozenset({"clef"})
    assert seen["purpose"] == "privacy"
    assert seen["timeout"] == 3.0
    assert set(seen["questions"]) == set(detector.PII_QUESTIONS)
    assert all(q["type"] == "noul" for q in seen["questions"].values())


def test_failure_means_not_scanned(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("clef down")

    monkeypatch.setattr(detector, "decide", boom)
    assert detector.detect_pii("我叫王小明") is None


def test_busy_slot_skips_instead_of_queueing(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(detector, "decide", lambda *a, **k: calls.append(1) or _answers())
    slot = detector._slot()
    slot.acquire()
    try:
        assert detector.detect_pii("我叫王小明") is None
    finally:
        slot.release()
    assert calls == []
    assert detector.detect_pii("我叫王小明") == {}


def test_blank_text_is_not_sent(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detector, "decide", lambda *a, **k: pytest.fail("should not ask"))
    assert detector.detect_pii("   ") == {}

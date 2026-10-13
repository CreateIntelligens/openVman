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


def test_only_clef_is_asked_gate_then_categories(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    # Jev 與 OpenAI 是外部服務：查個資不能把個資送出去，連備援都不行。
    calls = []

    def fake_decide(state, questions, **kwargs):
        calls.append((set(questions), kwargs))
        if "has_pii" in questions:
            return _answers(has_pii=0.9)
        return _answers(private_person=0.9, private_phone=0.2)

    monkeypatch.setattr(detector, "decide", fake_decide)

    assert detector.detect_pii("我叫王小明") == {"private_person": 1}
    assert [names for names, _ in calls] == [{"has_pii"}, set(detector.PII_QUESTIONS)]
    for _, kwargs in calls:
        assert kwargs["providers"] == frozenset({"clef"})
        assert kwargs["purpose"] == "privacy"
        assert kwargs["timeout"] == 3.0


def test_clean_message_costs_one_question(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    # 大部分訊息沒有個資：總判斷一題（約 0.11 秒）就結束，不再問 7 題。
    calls = []

    def fake_decide(state, questions, **kwargs):
        calls.append(set(questions))
        return _answers(has_pii=0.1)

    monkeypatch.setattr(detector, "decide", fake_decide)

    assert detector.detect_pii("請問要怎麼掛號？") == {}
    assert calls == [{"has_pii"}]


def test_gate_positive_without_category_still_warns(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_decide(state, questions, **kwargs):
        if "has_pii" in questions:
            return _answers(has_pii=0.8)
        return _answers(**{name: 0.1 for name in questions})

    monkeypatch.setattr(detector, "decide", fake_decide)

    assert detector.detect_pii("我的資料是這個") == {"unclassified": 1}


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

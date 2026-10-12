"""Reply picture chosen by the decision chain among retrieved candidates."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

import core.decision_router as decision_router
from core import reference_media
from core.decision_router import DecisionResult


def _row(question: str, image: str, distance: float, chunk: str | None = None) -> dict:
    return {
        "text": f"問題：{question}\n回答：…",
        "image_id": image,
        "_distance": distance,
        "chunk_id": chunk or question,
    }


def _steps(*rows: dict, name: str = "search_knowledge") -> list[dict]:
    return [{"name": name, "result": json.dumps({"status": "ok", "data": {"results": list(rows)}})}]


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    settings = SimpleNamespace(
        chat_reference_media_decision_enabled=True,
        chat_reference_media_timeout_seconds=1.0,
        chat_reference_media_min_confidence=0.6,
        turn_decisions_hop_timeout_seconds=0.6,
    )
    monkeypatch.setattr(reference_media, "get_settings", lambda: settings)
    return settings


def _answer(monkeypatch, choice: str, confidence: float = 0.9, calls: list | None = None):
    def fake_decide(state, questions, **kwargs):
        if calls is not None:
            calls.append((state, questions, kwargs))
        return DecisionResult({"pick": {"type": "choice", "choice": choice, "confidence": confidence}}, "clef", "clef-primary", "clef-flash")

    monkeypatch.setattr(decision_router, "decide", fake_decide)


def test_candidates_keep_pictures_only_closest_first_one_per_chunk_at_most_five():
    rows = [_row(f"Q{i}", f"p{i}.png", 0.9 - i * 0.1) for i in range(7)]
    steps = _steps(*rows, {"text": "無圖", "_distance": 0.0}, rows[0]) + _steps(_row("網路", "w.png", 0.0), name="search_web")

    candidates = reference_media.media_candidates(steps)

    assert [c["image_id"] for c in candidates] == ["p6.png", "p5.png", "p4.png", "p3.png", "p2.png"]


def test_shows_the_picked_candidate_even_when_it_is_not_the_closest(monkeypatch):
    calls = []
    _answer(monkeypatch, "c1", calls=calls)
    steps = _steps(_row("電源頻率", "page_01.png", 0.35), _row("EUSR 如何避免刮傷地面", "page_05.png", 0.47))

    media = reference_media.choose_reference_media("EUSR 會刮地嗎？", steps)

    assert media == {"image_id": "page_05.png"}
    state, questions, kwargs = calls[0]
    assert state == {"user_question": "EUSR 會刮地嗎？"}
    assert set(questions["pick"]["criteria"]) == {"c0", "c1", "none"}
    assert kwargs["purpose"] == "reference_media"


@pytest.mark.parametrize(("choice", "confidence"), [("none", 0.95), ("c0", 0.15)])
def test_no_picture_when_nothing_answers_or_the_model_is_unsure(monkeypatch, choice, confidence):
    _answer(monkeypatch, choice, confidence)
    steps = _steps(_row("電源頻率", "page_01.png", 0.35), _row("口徑", "page_05.png", 0.6))

    assert reference_media.choose_reference_media("我聽不懂，請一步一步說明", steps) == {}


def test_falls_back_when_disabled_failing_or_without_candidates(monkeypatch, _settings):
    steps = _steps(_row("電源頻率", "page_01.png", 0.35), _row("口徑", "page_05.png", 0.6))

    def broken(*args, **kwargs):
        raise decision_router.DecisionProviderError("down")

    monkeypatch.setattr(decision_router, "decide", broken)
    assert reference_media.choose_reference_media("問題", steps) is None
    assert reference_media.choose_reference_media("問題", []) is None
    _settings.chat_reference_media_decision_enabled = False
    _answer(monkeypatch, "c0")
    assert reference_media.choose_reference_media("問題", steps) is None


def test_background_choice_asks_once_per_candidate_set_and_follows_new_results(monkeypatch):
    calls = []
    release = threading.Event()

    def fake_decide(state, questions, **kwargs):
        calls.append(questions)
        release.wait(1)
        return DecisionResult({"pick": {"type": "choice", "choice": "c0", "confidence": 0.9}}, "clef", "clef-primary", "clef-flash")

    monkeypatch.setattr(decision_router, "decide", fake_decide)
    first = _steps(_row("A", "a.png", 0.3))
    choice = reference_media.ReplyMediaChoice("問題")

    choice.on_tool_round(first)
    choice.on_tool_round(list(first))
    release.set()
    assert choice.result(first) == {"image_id": "a.png"}
    assert len(calls) == 1

    second = first + _steps(_row("B", "b.png", 0.1))
    choice.on_tool_round(second)
    assert choice.result(second) == {"image_id": "b.png"}
    assert len(calls) == 2


def test_finalize_hides_citation_pictures_when_the_choice_differs(monkeypatch):
    from core import chat_service

    citations = [
        {"uri": "qa.csv", "title": "evak_qa", "image_id": "page_01.png", "distance": 0.3},
        {"uri": "catalog.md", "title": "catalog", "distance": 0.4},
    ]
    monkeypatch.setattr(chat_service, "_collect_citations_from_tool_steps", lambda steps: [dict(c) for c in citations])
    monkeypatch.setattr(chat_service, "_pii_writeback_executor", SimpleNamespace(submit=lambda *a, **k: None))
    context = SimpleNamespace(
        request_context={"metadata": {}}, trace_id="t", user_message="問題",
        turn_decision=None, session_id="s", persona_id="p", project_id="pr", prior_messages=[],
    )

    hidden = chat_service.finalize_generation(context, "回答", [], persist=False, media={})
    picked = chat_service.finalize_generation(context, "回答", [], persist=False, media={"image_id": "page_05.png"})
    kept = chat_service.finalize_generation(context, "回答", [], persist=False)

    assert "image_id" not in hidden and all("image_id" not in c for c in hidden["citations"])
    assert picked["image_id"] == "page_05.png"
    assert all("image_id" not in c for c in picked["citations"])
    assert kept["image_id"] == "page_01.png"

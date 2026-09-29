"""Streaming ASR: keep the final transcript unless Jev clearly prefers the interim."""

from __future__ import annotations

import types

import pytest

import core.jev_client as jev_client
import memory.asr_judge as asr_judge


@pytest.fixture
def jev(monkeypatch):
    cfg = types.SimpleNamespace(asr_final_judge_enabled=True, asr_final_judge_timeout_seconds=1.0)
    monkeypatch.setattr("config.get_settings", lambda: cfg)
    monkeypatch.setattr(jev_client, "jev_available", lambda: True)
    monkeypatch.setattr(asr_judge, "_project_context", lambda project_id: "這個專案的使用者可能說：繁體中文、英文、西班牙文。")
    calls: list[dict] = []

    def answer(scores):
        def fake(state, questions, *, timeout):
            calls.append({"state": state, "questions": questions, "timeout": timeout})
            if isinstance(scores, Exception):
                raise scores
            return scores
        monkeypatch.setattr(jev_client, "jev_nouls", fake)

    return types.SimpleNamespace(answer=answer, calls=calls, cfg=cfg)


def test_clearly_better_interim_replaces_a_garbled_final(jev):
    # 實際回報（2026-09-29）：講 who am i，定稿送出 OMI。
    jev.answer({"interim": 0.62, "final": 0.08})
    verdict = asr_judge.choose_transcript("p", "who am i", "OMI")
    assert (verdict.text, verdict.chosen) == ("who am i", "interim")
    questions = jev.calls[0]["questions"]
    assert "who am i" in questions["interim"]["instructions"]
    assert "OMI" in questions["final"]["instructions"]


def test_close_scores_keep_the_final(jev):
    jev.answer({"interim": 0.59, "final": 0.45})
    verdict = asr_judge.choose_transcript("p", "請問 DIVA 有攪拌器嗎", "請問低瓦有攪拌器嗎")
    assert verdict.chosen == "final"


def test_better_final_is_kept(jev):
    jev.answer({"interim": 0.04, "final": 0.9})
    assert asr_judge.choose_transcript("p", "who am", "Who am I?").text == "Who am I?"


@pytest.mark.parametrize("interim", ["", "Who am I", "who am i?"])
def test_same_or_missing_interim_skips_jev(jev, interim):
    jev.answer({"interim": 1.0, "final": 0.0})
    verdict = asr_judge.choose_transcript("p", interim, "Who am I?")
    assert verdict.text == "Who am I?"
    assert jev.calls == []


def test_jev_failure_or_disabled_keeps_the_final(jev):
    jev.answer(TimeoutError("slow"))
    assert asr_judge.choose_transcript("p", "who am i", "OMI").chosen == "final"
    jev.cfg.asr_final_judge_enabled = False
    jev.calls.clear()
    assert asr_judge.choose_transcript("p", "who am i", "OMI").chosen == "final"
    assert jev.calls == []


def test_context_lists_the_project_languages(monkeypatch):
    monkeypatch.setattr("knowledge.kb_settings.language_routes", lambda project_id: ["zh", "ko"])
    monkeypatch.setattr("infra.project_context.resolve_project_context", lambda project_id: (_ for _ in ()).throw(RuntimeError()))
    context = asr_judge._project_context("p")
    # 以後的日韓專案：韓文是正常結果，要寫進情境裡。
    assert "繁體中文、韓文" in context

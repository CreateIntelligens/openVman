"""core.turn_reads：HTTP 與 Live 共用的「這一輪先查什麼」。"""

from __future__ import annotations

import sys
import types

from core.turn_decisions import TurnDecision, TurnPolicy
from core.turn_reads import (
    knowledge_queries,
    message_text,
    planned_reads,
    previous_user_text,
    without_disabled_recall,
)


def test_message_text_keeps_only_string_text_parts():
    assert message_text("  你好 ") == "你好"
    assert message_text([
        {"type": "text", "text": "這台"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AA"}},
        {"type": "text", "text": None},
        {"type": "text", "text": "口徑呢？"},
    ]) == "這台\n口徑呢？"
    assert message_text(None) == ""


def test_previous_question_skips_this_turn_whether_or_not_it_was_stored():
    history = [
        {"role": "user", "content": "50EUBL 揚程多少？"},
        {"role": "assistant", "content": "12 m"},
    ]
    # HTTP：歷史不含這一句；Live：轉錄已寫進歷史
    assert previous_user_text(history, "那價格呢？") == "50EUBL 揚程多少？"
    stored = [*history, {"role": "user", "content": "那價格呢？"}]
    assert previous_user_text(stored, "那價格呢？") == "50EUBL 揚程多少？"
    assert previous_user_text([], "你好") == ""


def test_knowledge_queries_join_a_trimmed_previous_question():
    assert knowledge_queries("那價格呢？", "") == ["那價格呢？"]
    long_previous = "甲" * 300
    queries = knowledge_queries("那價格呢？", long_previous)
    assert queries == ["那價格呢？", f"{'甲' * 200}\n那價格呢？"]


def test_planned_reads_follow_the_decision_in_a_fixed_order():
    reads = planned_reads(
        current_text="今天匯率？", previous_text="", knowledge=True, web=True, memory=True,
    )
    assert reads == [
        ("search_knowledge", {"queries": ["今天匯率？"]}),
        ("search_web", {"query": "今天匯率？"}),
        ("search_memory", {"queries": ["今天匯率？"]}),
    ]
    assert planned_reads(current_text="", knowledge=True, web=True, memory=True) == []
    assert planned_reads(current_text="早安", knowledge=False, web=False, memory=False) == []


def test_disabled_recall_drops_a_positive_memory_read(monkeypatch):
    decision = TurnDecision(
        turn_id="t", policy=TurnPolicy(needs_memory=True, needs_knowledge=True), source="clef-primary",
    )
    monkeypatch.setitem(sys.modules, "memory.memory", types.SimpleNamespace(
        is_session_recall_disabled=lambda session_id, project_id: session_id == "off",
    ))

    off = without_disabled_recall(decision, "off", "p")
    assert off.policy.needs_memory is None
    assert off.policy.auto_recall is False
    assert off.policy.needs_knowledge is True
    assert without_disabled_recall(decision, "on", "p") is decision

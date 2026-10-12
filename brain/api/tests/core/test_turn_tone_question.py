from __future__ import annotations

from core.turn_decisions import TONES, build_turn_questions


def test_every_tone_option_describes_observable_cues():
    # 只寫一個字（"Confused."）時 Clef 只能猜字面，「我聽不懂，請一步一步說明」
    # 信心過不了門檻；每個選項都要寫出看得到的線索。
    criteria = build_turn_questions()["tone"]["criteria"]

    assert tuple(criteria) == TONES
    for tone, description in criteria.items():
        assert len(description.split()) >= 5, f"{tone} needs concrete cues, not a single word"
    assert "step-by-step" in criteria["confused"]
    assert "do not understand" in criteria["confused"]

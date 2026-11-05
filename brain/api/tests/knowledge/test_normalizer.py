"""Tests for the LLM markdown normalizer (knowledge.normalizer).

The real LLM is never called: ``core.llm_client`` (heavy: openai + provider
router) is stubbed at import time, and tests patch
``knowledge.normalizer.generate_chat_reply`` to assert call behavior.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


@pytest.fixture
def normalizer(monkeypatch):
    """Import knowledge.normalizer with heavy core.llm_client stubbed out.

    The stub goes in via monkeypatch.setitem so the real core.llm_client is
    restored after each test; knowledge.normalizer is evicted on teardown too,
    since its import bound symbols from the stub.
    """
    fake_llm = types.ModuleType("core.llm_client")
    fake_llm.generate_chat_reply = lambda messages: ""
    # graph_extractor (imported for _split_text) needs this symbol too.
    fake_llm.generate_chat_turn = lambda messages: None
    monkeypatch.setitem(sys.modules, "core.llm_client", fake_llm)

    sys.modules.pop("knowledge.normalizer", None)
    yield importlib.import_module("knowledge.normalizer")
    sys.modules.pop("knowledge.normalizer", None)


def test_single_short_segment_calls_llm_once(normalizer, monkeypatch):
    calls: list[str] = []

    def fake(messages):
        calls.append(messages[0]["content"])
        return "# 乾淨標題\n\n整理後內容。"

    monkeypatch.setattr("knowledge.normalizer.generate_chat_reply", fake)

    result = normalizer.normalize_to_markdown("## 誤判標題\n髒髒的內文")

    assert len(calls) == 1
    assert "髒髒的內文" in calls[0]  # raw text fed into the prompt
    assert result == "# 乾淨標題\n\n整理後內容。"


def test_long_input_splits_into_multiple_segments(normalizer, monkeypatch):
    # Build >6000 chars across many paragraphs so _split_text yields >1 segment.
    paragraphs = [f"段落{i}：" + "字" * 500 for i in range(20)]
    raw = "\n\n".join(paragraphs)
    assert len(raw) > 6000

    segments = normalizer._split_text(raw, size=normalizer.SEGMENT_SIZE)
    assert len(segments) > 1, "long input should split into >1 segment"

    seen_segments: list[str] = ["" for _ in segments]

    def fake(messages):
        content = messages[0]["content"]
        # Extract the segment exactly
        prefix = "待整理文字：\n---\n"
        start_idx = content.find(prefix)
        assert start_idx != -1
        extracted = content[start_idx + len(prefix):]
        end_idx = extracted.rfind("\n---")
        assert end_idx != -1
        seg = extracted[:end_idx]
        seg_len = len(seg)

        # Find which segment this is
        idx = -1
        for i, s in enumerate(segments):
            if s == seg:
                idx = i
                break
        assert idx != -1, "segment not found in precomputed segments"
        seen_segments[idx] = content
        prefix_out = f"CLEANED-{idx} "
        return prefix_out + "字" * (seg_len - len(prefix_out))

    monkeypatch.setattr("knowledge.normalizer.generate_chat_reply", fake)

    result = normalizer.normalize_to_markdown(raw)

    expected_parts = []
    for i, seg in enumerate(segments):
        prefix_out = f"CLEANED-{i} "
        expected_parts.append(prefix_out + "字" * (len(seg) - len(prefix_out)))
    expected = "\n\n".join(expected_parts)
    assert result == expected  # rejoined in order


def test_llm_failure_falls_back_to_original_segment(normalizer, monkeypatch):
    paragraphs = [f"段落{i}：" + "字" * 500 for i in range(20)]
    raw = "\n\n".join(paragraphs)
    segments = normalizer._split_text(raw, size=normalizer.SEGMENT_SIZE)
    assert len(segments) > 1

    fail_index = 1

    def fake(messages):
        content = messages[0]["content"]
        # Extract the segment exactly
        prefix = "待整理文字：\n---\n"
        start_idx = content.find(prefix)
        assert start_idx != -1
        extracted = content[start_idx + len(prefix):]
        end_idx = extracted.rfind("\n---")
        assert end_idx != -1
        seg = extracted[:end_idx]
        seg_len = len(seg)

        # Find which segment this is
        idx = -1
        for i, s in enumerate(segments):
            if s == seg:
                idx = i
                break
        assert idx != -1, "segment not found"

        if idx == fail_index:
            raise RuntimeError("simulated LLM failure")
        prefix_out = f"CLEANED-{idx} "
        return prefix_out + "字" * (seg_len - len(prefix_out))

    monkeypatch.setattr("knowledge.normalizer.generate_chat_reply", fake)

    result = normalizer.normalize_to_markdown(raw)

    # Failed segment -> original text preserved; others cleaned.
    assert segments[fail_index] in result
    assert "CLEANED-0" in result
    # No content lost: every original segment's text survives in the output
    # (failed one verbatim, others via their cleaned stand-ins which we trust).
    assert result.startswith("CLEANED-0")


def test_empty_input_returns_empty_without_calling_llm(normalizer, monkeypatch):
    def fake(messages):
        raise AssertionError("LLM should not be called for empty input")

    monkeypatch.setattr("knowledge.normalizer.generate_chat_reply", fake)

    assert normalizer.normalize_to_markdown("") == ""
    assert normalizer.normalize_to_markdown("   \n\t  ") == ""


def test_sanity_check_falls_back_on_truncated_output(normalizer, monkeypatch):
    original = "內" * 1000
    monkeypatch.setattr(
        "knowledge.normalizer.generate_chat_reply",
        lambda messages: "太短",
    )
    assert normalizer.normalize_to_markdown(original) == original


def test_strict_raises_instead_of_falling_back_when_llm_fails(normalizer, monkeypatch):
    """後台按「AI 整理排版」時退回原文，預覽就是原文，工作人員會以為整理過了。"""
    def fake(messages):
        raise RuntimeError("no LLM API key")

    monkeypatch.setattr("knowledge.normalizer.generate_chat_reply", fake)

    with pytest.raises(normalizer.NormalizationUnavailable, match="沒辦法使用"):
        normalizer.normalize_to_markdown("店內筆記\n老闆說冬天要多備貨。", strict=True)
    # 匯入維持原本的行為：退回原文、不中斷。
    assert normalizer.normalize_to_markdown("店內筆記\n老闆說冬天要多備貨。") == "店內筆記\n老闆說冬天要多備貨。"


def test_strict_raises_when_output_fails_sanity_check(normalizer, monkeypatch):
    monkeypatch.setattr(
        "knowledge.normalizer.generate_chat_reply",
        lambda messages: "太短",
    )
    with pytest.raises(normalizer.NormalizationUnavailable, match="差太多"):
        normalizer.normalize_to_markdown("內" * 1000, strict=True)


def test_sanity_check_falls_back_on_bloated_output(normalizer, monkeypatch):
    original = "內" * 1000
    monkeypatch.setattr(
        "knowledge.normalizer.generate_chat_reply",
        lambda messages: "灌" * 5000,
    )
    assert normalizer.normalize_to_markdown(original) == original


def test_short_segments_skip_the_length_check_only(normalizer, monkeypatch):
    monkeypatch.setattr(
        "knowledge.normalizer.generate_chat_reply",
        lambda messages: "這是一段變長了很多的短文，長度比例超出範圍也沒關係。",
    )
    assert normalizer.normalize_to_markdown("短文") == "這是一段變長了很多的短文，長度比例超出範圍也沒關係。"


_SPANISH_NOTE = (
    "Esta nota explica cómo cuidar la piel después del tratamiento. "
    "Por favor use protector solar todos los días y evite el sol por una semana."
)
_SPANISH_NOTE_IN_CHINESE = "這份筆記說明療程後如何照顧皮膚。請每天使用防曬，並避免日曬一週。"
_ENGLISH_NOTE = (
    "This note explains how to care for your skin after the treatment. "
    "Please use sunscreen every day and avoid the sun for a week."
)


def test_prompt_does_not_assume_chinese_and_forbids_translation(normalizer):
    prompt = normalizer.NORMALIZE_PROMPT
    assert "中文文字" not in prompt
    assert "不可翻譯" in prompt
    assert "每一段都維持它原本的語言" in prompt


@pytest.mark.parametrize("translated", [_SPANISH_NOTE_IN_CHINESE, _ENGLISH_NOTE])
def test_short_spanish_note_keeps_original_when_llm_translates(normalizer, monkeypatch, translated):
    assert len(_SPANISH_NOTE) < 500
    monkeypatch.setattr("knowledge.normalizer.generate_chat_reply", lambda messages: translated)
    assert normalizer.normalize_to_markdown(_SPANISH_NOTE) == _SPANISH_NOTE


def test_long_spanish_note_keeps_original_when_llm_translates(normalizer, monkeypatch):
    original = "\n\n".join([_SPANISH_NOTE] * 8)
    assert 500 < len(original) < normalizer.SEGMENT_SIZE
    monkeypatch.setattr(
        "knowledge.normalizer.generate_chat_reply",
        lambda messages: "\n\n".join([_SPANISH_NOTE_IN_CHINESE * 3] * 8),
    )
    assert normalizer.normalize_to_markdown(original) == original


def test_spanish_output_in_the_same_language_is_accepted(normalizer, monkeypatch):
    tidied = f"# Cuidado de la piel\n\n{_SPANISH_NOTE}"
    monkeypatch.setattr("knowledge.normalizer.generate_chat_reply", lambda messages: tidied)
    assert normalizer.normalize_to_markdown(_SPANISH_NOTE) == tidied


def test_chinese_note_keeps_original_when_llm_translates(normalizer, monkeypatch):
    monkeypatch.setattr("knowledge.normalizer.generate_chat_reply", lambda messages: _SPANISH_NOTE)
    assert normalizer.normalize_to_markdown(_SPANISH_NOTE_IN_CHINESE) == _SPANISH_NOTE_IN_CHINESE


@pytest.mark.parametrize(
    "original, translated",
    [("Bloqueador solar", "防曬乳"), ("防曬乳", "Bloqueador solar")],
)
def test_translation_of_text_too_short_to_detect_is_still_caught(
    normalizer, monkeypatch, original, translated,
):
    # 兩邊都判斷不出語言時都算中文，語言比對看不出差別。
    monkeypatch.setattr("knowledge.normalizer.generate_chat_reply", lambda messages: translated)
    assert normalizer.normalize_to_markdown(original) == original


def test_parallel_segments_preserve_order(normalizer, monkeypatch):
    text = "\n\n".join(f"SEG{tag} " + ("字" * 6500) for tag in ("A", "B", "C"))
    segments = normalizer._split_text(text, size=normalizer.SEGMENT_SIZE)

    def echo_segment(messages):
        content = messages[0]["content"]
        # Extract the segment exactly
        prefix = "待整理文字：\n---\n"
        start_idx = content.find(prefix)
        assert start_idx != -1
        extracted = content[start_idx + len(prefix):]
        end_idx = extracted.rfind("\n---")
        assert end_idx != -1
        seg = extracted[:end_idx]
        seg_len = len(seg)

        for marker in ("SEGA", "SEGB", "SEGC"):
            if marker in seg:
                prefix_out = f"cleaned-{marker} "
                return prefix_out + "字" * (seg_len - len(prefix_out))
        prefix_out = "cleaned-unknown "
        return prefix_out + "字" * (seg_len - len(prefix_out))

    monkeypatch.setattr("knowledge.normalizer.generate_chat_reply", echo_segment)
    result = normalizer.normalize_to_markdown(text)
    assert result.index("cleaned-SEGA") < result.index("cleaned-SEGB") < result.index("cleaned-SEGC")




